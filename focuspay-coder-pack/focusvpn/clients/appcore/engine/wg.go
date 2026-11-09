package engine

import (
	"context"
	"fmt"
	"sync"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun"
	"golang.zx2c4.com/wireguard/tun/tuntest"

	"focusvpn.example/focusvpn/clients/shared/tunnel"
)

// WGEngine drives plain WireGuard via embedded wireguard-go (MIT).
// Selected with FOCUSVPN_ENGINE=wireguard|wg. dryRun uses ChannelTUN.
type WGEngine struct {
	mu     sync.Mutex
	state  State
	dryRun bool
	dev    *device.Device
	tunDev tun.Device
}

// NewWG constructs the userspace WireGuard engine.
func NewWG(dryRun bool) *WGEngine {
	return &WGEngine{state: StateDisconnected, dryRun: dryRun}
}

// Prepare is a no-op for userspace WG.
func (e *WGEngine) Prepare(_ context.Context) error { return nil }

// Start applies AssembledConfig via WireGuard IpcSet (no Jc/Jmin/Jmax).
func (e *WGEngine) Start(_ context.Context, cfg AssembledConfig) error {
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

	uapi, err := tunnel.UAPIConfigWireGuard(tc)
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
			return fmt.Errorf("engine/wg: CreateTUN: %w (need CAP_NET_ADMIN, or use dry-run)", err)
		}
	}

	logger := device.NewLogger(device.LogLevelError, "(focusvpn-wg) ")
	dev := device.NewDevice(tunDev, conn.NewDefaultBind(), logger)
	if err := dev.IpcSet(uapi); err != nil {
		dev.Close()
		e.state = StateError
		return fmt.Errorf("engine/wg: IpcSet: %w", err)
	}
	if err := dev.Up(); err != nil {
		dev.Close()
		e.state = StateError
		return fmt.Errorf("engine/wg: Up: %w", err)
	}
	e.dev = dev
	e.tunDev = tunDev
	e.state = StateConnected
	return nil
}

// Stop closes the userspace device.
func (e *WGEngine) Stop(_ context.Context) error {
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
func (e *WGEngine) State() State {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.state
}

// Stats is empty until peer counters are exported.
func (e *WGEngine) Stats() (Stats, error) { return Stats{}, nil }

var _ VPNEngine = (*WGEngine)(nil)
