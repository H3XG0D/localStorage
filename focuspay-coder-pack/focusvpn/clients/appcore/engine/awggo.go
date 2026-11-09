package engine

import (
	"context"
	"fmt"
	"sync"

	"github.com/amnezia-vpn/amneziawg-go/conn"
	"github.com/amnezia-vpn/amneziawg-go/device"
	"github.com/amnezia-vpn/amneziawg-go/tun"
	"github.com/amnezia-vpn/amneziawg-go/tun/tuntest"

	"focusvpn.example/focusvpn/clients/shared/tunnel"
)

// GoEngine drives AmneziaWG via embedded amneziawg-go (MIT, pin v0.2.19).
// dryRun uses an in-memory ChannelTUN (no CAP_NET_ADMIN); otherwise CreateTUN.
type GoEngine struct {
	mu     sync.Mutex
	state  State
	dryRun bool
	dev    *device.Device
	tunDev tun.Device
}

// NewGo constructs the userspace AmneziaWG engine.
func NewGo(dryRun bool) *GoEngine {
	return &GoEngine{state: StateDisconnected, dryRun: dryRun}
}

// Prepare validates we can build UAPI later; always OK.
func (e *GoEngine) Prepare(_ context.Context) error { return nil }

// Start applies AssembledConfig via IpcSet and brings the device up.
func (e *GoEngine) Start(_ context.Context, cfg AssembledConfig) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.dev != nil {
		e.dev.Close()
		e.dev = nil
		e.tunDev = nil
	}
	e.state = StateConnecting

	tc := cfg.Tunnel
	ep, err := resolveEndpointForUAPI(tc.Endpoint, e.dryRun)
	if err != nil {
		e.state = StateError
		return err
	}
	tc.Endpoint = ep

	uapi, err := tunnel.UAPIConfig(tc)
	if err != nil {
		e.state = StateError
		return err
	}

	var tunDev tun.Device
	if e.dryRun {
		tunDev = tuntest.NewChannelTUN().TUN()
	} else {
		name := cfg.Tunnel.Interface
		if name == "" {
			name = "focusvpn0"
		}
		mtu := cfg.Tunnel.MTU
		if mtu <= 0 {
			mtu = device.DefaultMTU
		}
		tunDev, err = tun.CreateTUN(name, mtu)
		if err != nil {
			e.state = StateError
			return fmt.Errorf("engine/go: CreateTUN: %w (need CAP_NET_ADMIN, or use dry-run)", err)
		}
	}

	logger := device.NewLogger(device.LogLevelError, "(focusvpn-awg) ")
	dev := device.NewDevice(tunDev, conn.NewDefaultBind(), logger)
	if err := dev.IpcSet(uapi); err != nil {
		dev.Close()
		e.state = StateError
		return fmt.Errorf("engine/go: IpcSet: %w", err)
	}
	if err := dev.Up(); err != nil {
		dev.Close()
		e.state = StateError
		return fmt.Errorf("engine/go: Up: %w", err)
	}
	e.dev = dev
	e.tunDev = tunDev
	e.state = StateConnected
	return nil
}

// Stop closes the userspace device.
func (e *GoEngine) Stop(_ context.Context) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.dev != nil {
		e.dev.Close()
		e.dev = nil
		e.tunDev = nil
	}
	e.state = StateDisconnected
	return nil
}

// State returns the lifecycle state.
func (e *GoEngine) State() State {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.state
}

// Stats is empty until peer counters are exported.
func (e *GoEngine) Stats() (Stats, error) { return Stats{}, nil }

var _ VPNEngine = (*GoEngine)(nil)
