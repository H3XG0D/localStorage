// Package client is the AppCore façade wiring auth, device, config, and VPNEngine.
package client

import (
	"context"
	"crypto/ed25519"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"focusvpn.example/focusvpn/clients/appcore/apierr"
	"focusvpn.example/focusvpn/clients/appcore/auth"
	"focusvpn.example/focusvpn/clients/appcore/config"
	"focusvpn.example/focusvpn/clients/appcore/connectivity"
	"focusvpn.example/focusvpn/clients/appcore/device"
	"focusvpn.example/focusvpn/clients/appcore/engine"
	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
	"focusvpn.example/focusvpn/clients/shared/tunnel"
	"focusvpn.example/focusvpn/clients/shared/xray"

	"github.com/google/uuid"
)

// Options configure an AppCore client.
type Options struct {
	APIBase        string
	Store          storage.SecureStorage
	Engine         engine.VPNEngine
	VerifyPubKey   ed25519.PublicKey // optional
	Interface      string
	ConfDir        string
	DeviceName     string
	DevicePlatform string
	DryRun         bool
	// Sleep is used between failover attempts (tests inject no-op / short sleeps).
	Sleep func(time.Duration)
	// DisableFailover forces a single connect attempt (debug).
	DisableFailover bool
	// FailoverBase/Cap override connectivity defaults when > 0 (tests use ms).
	FailoverBase time.Duration
	FailoverCap  time.Duration
}

// App is the product-facing AppCore handle.
type App struct {
	opts   Options
	auth   *auth.Service
	device *device.Service
	config *config.Service
}

// New builds an App.
func New(opts Options) (*App, error) {
	if opts.APIBase == "" {
		return nil, fmt.Errorf("appcore: APIBase required")
	}
	if opts.Store == nil {
		return nil, fmt.Errorf("appcore: Store required")
	}
	if opts.Engine == nil {
		return nil, fmt.Errorf("appcore: Engine required")
	}
	if opts.Interface == "" {
		opts.Interface = "focusvpn0"
	}
	if opts.DeviceName == "" {
		opts.DeviceName = "linux"
	}
	if opts.DevicePlatform == "" {
		opts.DevicePlatform = "linux"
	}
	if opts.ConfDir == "" {
		opts.ConfDir = filepath.Join(os.TempDir(), "focusvpn-conf")
	}
	if opts.Sleep == nil {
		opts.Sleep = time.Sleep
	}
	_ = opts.Store.Set(storage.KeyAPIBase, []byte(opts.APIBase))
	return &App{
		opts:   opts,
		auth:   auth.New(opts.APIBase, opts.Store),
		device: device.New(opts.APIBase, opts.Store),
		config: config.New(opts.APIBase, opts.Store, opts.VerifyPubKey, opts.Interface),
	}, nil
}

// Login registers-or-logs-in then ensures a device identity.
func (a *App) Login(ctx context.Context, email, password string) error {
	if err := a.auth.Login(ctx, email, password); err != nil {
		// try register then login for first-run convenience in smoke
		if err2 := a.auth.Register(ctx, email, password); err2 != nil {
			return err
		}
	}
	_ = a.opts.Store.Set(storage.KeyEmail, []byte(email))
	access, err := a.auth.AccessToken()
	if err != nil {
		return err
	}
	_, _, err = a.device.EnsureDevice(ctx, access, a.opts.DeviceName, a.opts.DevicePlatform)
	return err
}

// Register creates an account (explicit).
func (a *App) Register(ctx context.Context, email, password string) error {
	if err := a.auth.Register(ctx, email, password); err != nil {
		return err
	}
	_ = a.opts.Store.Set(storage.KeyEmail, []byte(email))
	access, err := a.auth.AccessToken()
	if err != nil {
		return err
	}
	_, _, err = a.device.EnsureDevice(ctx, access, a.opts.DeviceName, a.opts.DevicePlatform)
	return err
}

// Logout clears session.
func (a *App) Logout(ctx context.Context) error {
	_ = a.opts.Store.Delete(storage.KeyEmail)
	_ = a.opts.Store.Delete(storage.KeySelectedNode)
	_ = a.opts.Store.Delete(storage.KeyCandidates)
	return a.auth.Logout(ctx)
}

// Status reports session + tunnel state.
type Status struct {
	LoggedIn     bool         `json:"logged_in"`
	State        engine.State `json:"state"`
	APIBase      string       `json:"api_base"`
	Email        string       `json:"email,omitempty"`
	SelectedNode string       `json:"selected_node,omitempty"`
	Plan         string       `json:"plan,omitempty"`
	EndsAt       string       `json:"ends_at,omitempty"`
	MaxDevices   int          `json:"max_devices,omitempty"`
	DevicesUsed  int          `json:"devices_used,omitempty"`
}

// AccountView is GET /v1/me plus the device list for the account screen.
type AccountView struct {
	Email       string               `json:"email,omitempty"`
	Plan        string               `json:"plan,omitempty"`
	Status      string               `json:"status,omitempty"`
	EndsAt      string               `json:"ends_at,omitempty"`
	MaxDevices  int                  `json:"max_devices,omitempty"`
	DevicesUsed int                  `json:"devices_used,omitempty"`
	Devices     []apitypes.DeviceDTO `json:"devices,omitempty"`
}

// Status reports session + tunnel state.
func (a *App) Status() Status {
	access, err := a.auth.EnsureAccess(context.Background())
	email, _ := a.opts.Store.Get(storage.KeyEmail)
	node, _ := a.opts.Store.Get(storage.KeySelectedNode)
	state := a.opts.Engine.State()
	// Persist UX across CLI process restarts: live allocation implies connected.
	if state == engine.StateDisconnected {
		if cid, e := a.opts.Store.Get(storage.KeyConnectionID); e == nil && len(cid) > 0 {
			state = engine.StateConnected
		}
	}
	out := Status{
		LoggedIn:     err == nil,
		State:        state,
		APIBase:      a.opts.APIBase,
		Email:        string(email),
		SelectedNode: string(node),
	}
	if err != nil {
		return out
	}
	me, meErr := a.auth.Me(context.Background(), access)
	if meErr != nil || me.Subscription == nil {
		return out
	}
	out.Plan = me.Subscription.Plan
	out.EndsAt = me.Subscription.EndsAt
	out.MaxDevices = me.Subscription.MaxDevices
	out.DevicesUsed = me.Subscription.DevicesUsed
	if me.User.Email != "" {
		out.Email = me.User.Email
	}
	return out
}

// EngineState is the local tunnel state and does not call the control plane.
func (a *App) EngineState() string {
	if a.opts.Engine == nil {
		return string(engine.StateDisconnected)
	}
	return string(a.opts.Engine.State())
}

// ListServers returns selectable VPN endpoints from the control plane.
func (a *App) ListServers(ctx context.Context) (apitypes.ServersResponse, error) {
	var out apitypes.ServersResponse
	err := a.callWithAccess(ctx, func(access string) error {
		var err error
		out, err = a.config.ListServers(ctx, access)
		return err
	})
	return out, err
}

// StartTelegram begins a deep-link login.
func (a *App) StartTelegram(ctx context.Context) (auth.TelegramStart, error) {
	return a.auth.TelegramStart(ctx)
}

// WaitTelegram polls a pending Telegram login and registers this device once it lands.
func (a *App) WaitTelegram(ctx context.Context, waitToken string) (bool, error) {
	resp, ready, err := a.auth.TelegramWait(ctx, waitToken)
	if err != nil || !ready {
		return ready, err
	}
	return true, a.adoptSession(ctx, resp.User.Email)
}

// LoginWithCode redeems a bot access code and registers this device.
func (a *App) LoginWithCode(ctx context.Context, code string) error {
	resp, err := a.auth.LoginCode(ctx, code)
	if err != nil {
		return err
	}
	return a.adoptSession(ctx, resp.User.Email)
}

// Account loads subscription and devices.
func (a *App) Account(ctx context.Context) (AccountView, error) {
	var view AccountView
	err := a.callWithAccess(ctx, func(access string) error {
		me, err := a.auth.Me(ctx, access)
		if err != nil {
			return err
		}
		view.Email = me.User.Email
		if me.Subscription != nil {
			view.Plan = me.Subscription.Plan
			view.Status = me.Subscription.Status
			view.EndsAt = me.Subscription.EndsAt
			view.MaxDevices = me.Subscription.MaxDevices
			view.DevicesUsed = me.Subscription.DevicesUsed
		}
		list, err := a.auth.ListDevices(ctx, access)
		if err != nil {
			return err
		}
		view.Devices = list.Devices
		return nil
	})
	if view.Email != "" {
		_ = a.opts.Store.Set(storage.KeyEmail, []byte(view.Email))
	}
	return view, err
}

func (a *App) adoptSession(ctx context.Context, email string) error {
	if email != "" {
		_ = a.opts.Store.Set(storage.KeyEmail, []byte(email))
	}
	access, err := a.auth.EnsureAccess(ctx)
	if err != nil {
		return err
	}
	_, _, err = a.device.EnsureDevice(ctx, access, a.opts.DeviceName, a.opts.DevicePlatform)
	return err
}

func (a *App) callWithAccess(ctx context.Context, fn func(access string) error) error {
	access, err := a.auth.EnsureAccess(ctx)
	if err != nil {
		return fmt.Errorf("appcore: not logged in")
	}
	err = fn(access)
	if !apierr.IsAccessRejected(err) {
		return err
	}
	access, err = a.auth.RefreshAfterReject(ctx, access)
	if err != nil {
		return err
	}
	return fn(access)
}

// SelectNode remembers the user's preferred endpoint node id/code for the UI.
func (a *App) SelectNode(node string) error {
	if node == "" {
		return a.opts.Store.Delete(storage.KeySelectedNode)
	}
	return a.opts.Store.Set(storage.KeySelectedNode, []byte(node))
}

// Connect provisions CP allocation, writes conf, starts engine (or dry-run).
// On engine Start failure, walks CP candidates with backoff and may refresh the list (§10.3).
func (a *App) Connect(ctx context.Context) (config.ConnectResult, error) {
	preferred, _ := a.opts.Store.Get(storage.KeySelectedNode)
	preferredNode := string(preferred)

	res, err := a.connectOnce(ctx, preferredNode)
	if err == nil || a.opts.DisableFailover {
		return res, err
	}
	// CP-level failures (no candidates) — do not walk.
	if len(res.Candidates) == 0 {
		return res, err
	}

	plan := connectivity.NewPlan(res.Candidates)
	a.applyFailoverTiming(&plan)
	failedID := ""
	if len(res.Candidates) > 0 {
		failedID = res.Candidates[0].Endpoint.ID
	}
	plan.AfterFailure(failedID)

	lastErr := err
	refreshed := false
	for {
		if err := ctx.Err(); err != nil {
			return res, err
		}
		idx, delay, refreshCP, exhausted := plan.Next()
		if exhausted {
			return res, fmt.Errorf("appcore: failover exhausted: %w", lastErr)
		}
		a.opts.Sleep(delay)
		a.revokeForFailover(ctx)

		nextPreferred := ""
		if refreshCP {
			if refreshed {
				return res, fmt.Errorf("appcore: failover refresh exhausted: %w", lastErr)
			}
			refreshed = true
			nextPreferred = "" // fresh CP ranking
		} else {
			nextPreferred = connectivity.PreferredNode(plan.Candidates[idx])
		}

		res, err = a.connectOnce(ctx, nextPreferred)
		if err == nil {
			return res, nil
		}
		lastErr = err
		if len(res.Candidates) == 0 {
			return res, lastErr
		}
		if refreshCP {
			plan = connectivity.NewPlan(res.Candidates)
			a.applyFailoverTiming(&plan)
			plan.AfterFailure(res.Candidates[0].Endpoint.ID)
		}
	}
}

func (a *App) applyFailoverTiming(plan *connectivity.Plan) {
	if a.opts.FailoverBase > 0 {
		plan.Base = a.opts.FailoverBase
	}
	if a.opts.FailoverCap > 0 {
		plan.Cap = a.opts.FailoverCap
	}
}

// desktopTunnelServer prefers WebSocket. XHTTP packet-up appends a session id,
// and the node fallback only accepts the exact path, so that first entry hits
// the decoy site. The phone walks the list; the desktop tun dials one server.
func desktopTunnelServer(servers []xray.VlessServer) xray.VlessServer {
	for _, server := range servers {
		if server.Transport == "ws" {
			return server
		}
	}
	return servers[0]
}

func (a *App) connectOnce(ctx context.Context, preferredNode string) (config.ConnectResult, error) {
	access, err := a.auth.EnsureAccess(ctx)
	if err != nil {
		return config.ConnectResult{}, fmt.Errorf("appcore: not logged in")
	}
	devID, err := a.opts.Store.Get(storage.KeyDeviceID)
	if err != nil {
		return config.ConnectResult{}, fmt.Errorf("appcore: no device: %w", err)
	}
	devTok, err := a.opts.Store.Get(storage.KeyDeviceToken)
	if err != nil {
		return config.ConnectResult{}, err
	}
	priv, err := a.device.PrivateKeyB64()
	if err != nil {
		return config.ConnectResult{}, err
	}
	protocol := "amneziawg"
	if _, ok := a.opts.Engine.(*engine.XrayEngine); ok {
		protocol = "vless"
	}
	res, err := a.config.Connect(ctx, access, string(devID), string(devTok), priv, preferredNode, protocol)
	if apierr.IsAccessRejected(err) {
		access, err = a.auth.RefreshAfterReject(ctx, access)
		if err != nil {
			return config.ConnectResult{}, err
		}
		res, err = a.config.Connect(ctx, access, string(devID), string(devTok), priv, preferredNode, protocol)
	}
	if err != nil {
		return res, err
	}
	res.Assembled.ConfDir = a.opts.ConfDir

	switch a.opts.Engine.(type) {
	case *engine.XrayEngine:
		if prof, perr := xray.ProfileFromParts(res.Parts); perr == nil {
			prefixes, err := xray.LoadRUPrefixes()
			if err != nil {
				return res, fmt.Errorf("appcore: ru prefixes: %w", err)
			}
			server := desktopTunnelServer(prof.Servers)
			path, err := xray.WriteTunJSON(a.opts.ConfDir, "xray-client.json", server, prof.UUID, prefixes)
			if err != nil {
				return res, err
			}
			res.Assembled.Xray = nil
			res.Assembled.ConfPath = path
			break
		} else if !a.opts.DryRun {
			return res, perr
		}
		vlessID := uuid.NewSHA1(uuid.NameSpaceURL, []byte("focusvpn:vless:"+string(devID))).String()
		ep := res.Assembled.Tunnel.Endpoint
		if ep == "" {
			ep = "127.0.0.1:443"
		}
		xc, xerr := xray.SyntheticForDryRun(ep, vlessID)
		if xerr != nil {
			return res, xerr
		}
		path, err := xray.WriteJSON(a.opts.ConfDir, "xray-client.json", xc)
		if err != nil {
			return res, err
		}
		res.Assembled.Xray = &xc
		res.Assembled.ConfPath = path
	default:
		path, err := tunnel.WriteConf(a.opts.ConfDir, res.Assembled.Tunnel)
		if err != nil {
			return res, err
		}
		res.Assembled.ConfPath = path
	}
	_ = a.opts.Store.Set(storage.KeyConfPath, []byte(res.Assembled.ConfPath))

	if err := a.opts.Engine.Prepare(ctx); err != nil {
		return res, err
	}
	if err := a.opts.Engine.Start(ctx, res.Assembled); err != nil {
		_ = a.opts.Engine.Stop(ctx)
		return res, err
	}
	return res, nil
}

// revokeForFailover best-effort clears local + CP allocation so the next attempt can create.
func (a *App) revokeForFailover(ctx context.Context) {
	_ = a.opts.Engine.Stop(ctx)
	access, err := a.auth.EnsureAccess(ctx)
	if err != nil {
		_ = a.opts.Store.Delete(storage.KeyConnectionID)
		return
	}
	if cid, err := a.opts.Store.Get(storage.KeyConnectionID); err == nil {
		_ = a.config.Disconnect(ctx, access, string(cid))
	}
	_ = a.opts.Store.Delete(storage.KeyConnectionID)
}

// Disconnect stops the engine and revokes the CP connection.
func (a *App) Disconnect(ctx context.Context) error {
	_ = a.opts.Engine.Stop(ctx)
	access, err := a.auth.EnsureAccess(ctx)
	if err != nil {
		return nil
	}
	cid, err := a.opts.Store.Get(storage.KeyConnectionID)
	if err != nil {
		return nil
	}
	if err := a.config.Disconnect(ctx, access, string(cid)); err != nil {
		return err
	}
	_ = a.opts.Store.Delete(storage.KeyConnectionID)
	return nil
}
