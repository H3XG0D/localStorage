// Command server is the FocusVPN Control Plane (modular monolith, ADR-001).
package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/ca"
	"focusvpn.example/focusvpn/backend/internal/platform/config"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
	"focusvpn.example/focusvpn/backend/internal/platform/store/postgres"
	"focusvpn.example/focusvpn/backend/internal/server"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	var st store.Store
	switch cfg.Store {
	case "memory":
		// Test/dev/smoke store only — never the production source of truth.
		ms := memory.New()
		ms.UseKEK(mycrypto.KEK{ID: cfg.KEKID, Key: cfg.KEKKey})
		if os.Getenv("FOCUSVPN_MEMORY_SEED") == "1" || os.Getenv("FOCUSVPN_MEMORY_SEED") == "true" {
			ms.SeedSmokeCatalog()
		}
		st = ms
	case "postgres":
		// PostgreSQL is the production source of truth. If it is configured but
		// unreachable we fail loudly and NEVER silently downgrade to memory
		// (M2 IMPLEMENTATION RULES / DECISIONS.md).
		pg, perr := postgres.New(context.Background(), cfg.DatabaseURL)
		if perr != nil {
			log.Fatalf("store=postgres: %v", perr)
		}
		pg.UseKEK(mycrypto.KEK{ID: cfg.KEKID, Key: cfg.KEKKey})
		st = pg
	default:
		log.Fatalf("unsupported FOCUSVPN_STORE=%q (supported: memory, postgres)", cfg.Store)
	}
	defer func() { _ = st.Close() }()

	// M4: load CA for node-agent mTLS listener.
	authority, err := ca.Load(cfg.AgentCACert, cfg.AgentCAKey)
	if err != nil {
		log.Fatalf("ca: %v", err)
	}

	deps := server.Deps{
		Config:  cfg,
		Store:   st,
		Limiter: ratelimit.NewMemory(),
		CA:      authority,
	}

	result := server.New(deps)
	if result.Scheduler != nil {
		result.Scheduler.Start()
		defer result.Scheduler.Stop()
		log.Printf("scheduler: config TTL=%s interval=%s", cfg.ConfigTTL, cfg.SchedulerInterval)
	}
	srv := server.HTTPServer(cfg.HTTPAddr, result.Handler)

	go func() {
		log.Printf("FocusVPN control plane listening on %s (store=%s)", cfg.HTTPAddr, cfg.Store)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("http server: %v", err)
		}
	}()

	// M4: agent mTLS listener (skip when FOCUSVPN_AGENT_ADDR=off).
	if cfg.AgentAddr != "" {
		if agentHandler := server.NewAgentHandler(result.AgentHandler); agentHandler != nil {
			tlsName := os.Getenv("FOCUSVPN_AGENT_TLS_NAME")
			if tlsName == "" {
				tlsName = "cp.focusvpn.internal"
			}
			serverCert, err := authority.GenerateServerCert(tlsName, 365*24*time.Hour)
			if err != nil {
				log.Fatalf("agent listener: generate server cert: %v", err)
			}
			tlsCfg := authority.TLSConfig(serverCert)
			agentSrv := &http.Server{
				Addr:              cfg.AgentAddr,
				Handler:           agentHandler,
				TLSConfig:         tlsCfg,
				ReadHeaderTimeout: 10 * time.Second,
				ReadTimeout:       35 * time.Second, // > long-poll timeout
				WriteTimeout:      35 * time.Second,
				IdleTimeout:       60 * time.Second,
			}
			go func() {
				log.Printf("FocusVPN agent listener (mTLS) on %s", cfg.AgentAddr)
				if err := agentSrv.ListenAndServeTLS("", ""); err != nil && !errors.Is(err, http.ErrServerClosed) {
					log.Printf("agent listener: %v", err)
				}
			}()
			defer func() {
				ctx2, cancel2 := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel2()
				_ = agentSrv.Shutdown(ctx2)
			}()
		}
	}

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("graceful shutdown failed: %v", err)
	}
	log.Println("server stopped")
}
