// Package server wires the Control Plane modules into a single http.Handler
// (modular monolith, ADR-001).
package server

import (
	"net/http"
	"time"

	"focusvpn.example/focusvpn/backend/internal/applogin"
	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/billing"
	"focusvpn.example/focusvpn/backend/internal/configurations"
	"focusvpn.example/focusvpn/backend/internal/connections"
	"focusvpn.example/focusvpn/backend/internal/devices"
	"focusvpn.example/focusvpn/backend/internal/nodeagent"
	"focusvpn.example/focusvpn/backend/internal/nodereg"
	"focusvpn.example/focusvpn/backend/internal/platform/ca"
	"focusvpn.example/focusvpn/backend/internal/platform/config"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/scheduler"
	"focusvpn.example/focusvpn/backend/internal/servers"
	"focusvpn.example/focusvpn/backend/internal/sublink"
	"focusvpn.example/focusvpn/backend/internal/users"
)

// Deps are the collaborators required to build the HTTP handler.
type Deps struct {
	Config  config.Config
	Store   store.Store
	Limiter ratelimit.Limiter
	CA      *ca.CA // optional; required for node-agent listener
}

// NewResult bundles the user-facing handler and (optionally) the agent handler.
type NewResult struct {
	Handler      http.Handler
	AgentHandler *nodeagent.Handler // nil if no CA configured
	Scheduler    *scheduler.Scheduler
}

// New builds the top-level http.Handler with middleware applied.
func New(d Deps) NewResult {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/health", httpx.Health)

	issuer := auth.NewTokenIssuer(d.Config.JWTPrivateKey, d.Config.JWTPublicKey, d.Config.TokenHMACKey, d.Config.AccessTTL)
	authSvc := auth.NewService(d.Store.Users(), d.Store.Refresh(), issuer, d.Config.RefreshTTL)
	auth.NewHandler(authSvc, d.Limiter, d.Config.RateLimits).Routes(mux)

	authn := auth.NewAuthenticator(issuer, d.Limiter, d.Config.RateLimits.GeneralPerMinutePerToken)
	users.NewHandler(d.Store.Users(), d.Store.Subscriptions(), d.Store.Devices(), authn).Routes(mux)
	deviceSvc := devices.NewService(d.Store.Devices(), d.Store.Subscriptions(), issuer)

	servers.NewHandler(d.Store.Endpoints(), d.Store.Subscriptions(), authn).Routes(mux)

	kek := mycrypto.KEK{ID: d.Config.KEKID, Key: d.Config.KEKKey}
	signer := mycrypto.NewConfigSigner(d.Config.ConfigSigningPrivateKey)

	var agentNotifier connections.StateNotifier
	var agentHandler *nodeagent.Handler
	if d.CA != nil {
		agentHandler = nodeagent.New(d.CA, d.Store)
		agentNotifier = agentHandler
	}

	connSvc := connections.NewService(
		d.Store.Devices(), d.Store.Endpoints(), d.Store.Allocations(), d.Store.Configurations(),
		d.Store.Subscriptions(), d.Store.NodeState(), kek, signer, d.Config.AllocationAutoActive,
		agentNotifier,
	)
	connections.NewHandler(connSvc, authn).Routes(mux)

	deviceAuth := auth.NewDeviceAuthenticator(d.Store.Devices(), issuer)
	deviceSvc.SetRotation(d.Store.Allocations(), d.Store.Configurations(), connSvc)
	devices.NewHandler(deviceSvc, authn, deviceAuth).Routes(mux)
	sublink.NewHandler(sublink.NewService(
		d.Store.SubLinks(), d.Store.Users(), d.Store.Subscriptions(), d.Store.Devices(),
		deviceSvc, connSvc, kek, issuer.HashRefresh,
		d.Config.PublicBase, d.Config.TelegramBotUsername,
	), d.Limiter, d.Config.InternalToken).Routes(mux)
	configurations.NewHandler(d.Store.Configurations(), d.Store.Subscriptions(), deviceAuth, map[string]mycrypto.KEK{kek.ID: kek}).Routes(mux)

	billSvc := billing.New(d.Store.Users(), d.Store.Subscriptions())
	billSvc.UseDevices(deviceSvc, d.Store.Allocations(), devices.ErrNotFound)
	billing.NewHandler(billSvc, d.Config.InternalToken).Routes(mux)

	appLoginSvc := applogin.NewService(
		d.Store.AppLogins(), d.Store.Users(), billSvc, authSvc, issuer.HashRefresh,
		d.Config.TelegramBotUsername, d.Config.AppLoginTTL,
	)
	applogin.NewHandler(appLoginSvc, d.Limiter, d.Config.InternalToken).Routes(mux)
	nodereg.NewHandler(d.Store.Nodes(), d.Store.NodeTokens(), d.Store.Reports(), d.Config.InternalToken).Routes(mux)

	var sched *scheduler.Scheduler
	if d.Config.SchedulerEnabled {
		sched = scheduler.New(connSvc, scheduler.Options{
			Interval:  d.Config.SchedulerInterval,
			ConfigTTL: d.Config.ConfigTTL,
			Expirer:   d.Store.Subscriptions(),
		})
	}

	return NewResult{
		Handler:      httpx.WithRequestID(httpx.Recover(mux)),
		AgentHandler: agentHandler,
		Scheduler:    sched,
	}
}

// NewAgentHandler builds the mTLS-protected http.Handler for the node-agent
// listener. Returns nil if no CA is configured (agent listener disabled).
// NOTE: call New() first to ensure agentHandler is shared with connections service.
// This function is intentionally kept separate so the main listener can use the
// same nodeagent.Handler instance.
func NewAgentHandler(h *nodeagent.Handler) http.Handler {
	if h == nil {
		return nil
	}
	mux := http.NewServeMux()
	h.Routes(mux)
	return httpx.WithRequestID(httpx.Recover(mux))
}

// HTTPServer returns a configured *http.Server with sane timeouts.
func HTTPServer(addr string, h http.Handler) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           h,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
}
