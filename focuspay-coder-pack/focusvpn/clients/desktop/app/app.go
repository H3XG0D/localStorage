// Package app is the desktop (Wails) façade over AppCore.
package app

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	appclient "focusvpn.example/focusvpn/clients/appcore/client"
	"focusvpn.example/focusvpn/clients/appcore/config"
	"focusvpn.example/focusvpn/clients/appcore/engine"
	appruntime "focusvpn.example/focusvpn/clients/appcore/runtime"
	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Options configure the desktop App bindings.
type Options struct {
	APIBase string
	DataDir string
	ConfDir string
	DryRun  bool
	// Engine overrides the default AmneziaWG engine. The GUI passes "xray".
	Engine string
}

// App exposes methods bound to the Wails frontend (and headless smoke CLI).
type App struct {
	mu   sync.Mutex
	opts Options
	core *appclient.App
	xray *engine.XrayEngine
}

// New constructs desktop bindings. Core is opened lazily on first auth/API call
// so the UI can change API base before login.
func New(opts Options) *App {
	if opts.APIBase == "" {
		opts.APIBase = "http://localhost:8080"
	}
	return &App{opts: opts}
}

func (a *App) openLocked() (*appclient.App, error) {
	if a.core != nil {
		return a.core, nil
	}
	st, err := storage.NewFileStore(a.opts.DataDir)
	if err != nil {
		return nil, err
	}
	a.opts.DataDir = st.Dir()
	if rep := appruntime.Inspect(a.opts.DataDir); rep.XrayPath != "" {
		_ = os.Setenv("XRAY_BIN", rep.XrayPath)
	}
	if b, err := st.Get(storage.KeyAPIBase); err == nil && len(b) > 0 && a.opts.APIBase == "http://localhost:8080" {
		a.opts.APIBase = string(b)
	}
	confDir := a.opts.ConfDir
	if confDir == "" {
		confDir = filepath.Join(st.Dir(), "conf")
	}
	eng := engine.NewDefault(a.opts.DryRun)
	if a.opts.Engine != "" {
		eng = engine.NewNamed(a.opts.Engine, a.opts.DryRun)
	}
	if x, ok := eng.(*engine.XrayEngine); ok {
		a.xray = x
	}
	core, err := appclient.New(appclient.Options{
		APIBase:        a.opts.APIBase,
		Store:          st,
		Engine:         eng,
		ConfDir:        confDir,
		DryRun:         a.opts.DryRun,
		DeviceName:     "desktop",
		DevicePlatform: "linux",
	})
	if err != nil {
		return nil, err
	}
	a.core = core
	return a.core, nil
}

// SetAPIBase updates the control plane URL (before login). Resets the core handle.
func (a *App) SetAPIBase(api string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if api == "" {
		return fmt.Errorf("api base required")
	}
	a.opts.APIBase = api
	a.core = nil
	return nil
}

// Login authenticates and ensures a device.
func (a *App) Login(email, password string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return err
	}
	return core.Login(context.Background(), email, password)
}

// Register creates an account and device.
func (a *App) Register(email, password string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return err
	}
	return core.Register(context.Background(), email, password)
}

// Logout clears the session.
func (a *App) Logout() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return err
	}
	err = core.Logout(context.Background())
	a.core = nil
	return err
}

// StatusDTO is JSON-friendly status for the UI.
type StatusDTO struct {
	LoggedIn     bool   `json:"logged_in"`
	State        string `json:"state"`
	APIBase      string `json:"api_base"`
	Email        string `json:"email,omitempty"`
	SelectedNode string `json:"selected_node,omitempty"`
	Plan         string `json:"plan,omitempty"`
	EndsAt       string `json:"ends_at,omitempty"`
	MaxDevices   int    `json:"max_devices,omitempty"`
	DevicesUsed  int    `json:"devices_used,omitempty"`
}

// Status returns session + tunnel state.
func (a *App) Status() StatusDTO {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return StatusDTO{State: string(engine.StateDisconnected), APIBase: a.opts.APIBase}
	}
	st := core.Status()
	return StatusDTO{
		LoggedIn:     st.LoggedIn,
		State:        string(st.State),
		APIBase:      st.APIBase,
		Email:        st.Email,
		SelectedNode: st.SelectedNode,
		Plan:         st.Plan,
		EndsAt:       st.EndsAt,
		MaxDevices:   st.MaxDevices,
		DevicesUsed:  st.DevicesUsed,
	}
}

// ListServers returns selectable endpoints.
func (a *App) ListServers() (apitypes.ServersResponse, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return apitypes.ServersResponse{}, err
	}
	return core.ListServers(context.Background())
}

// SelectNode remembers the preferred location for the Home screen.
func (a *App) SelectNode(node string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return err
	}
	return core.SelectNode(node)
}

// ConnectResultDTO is returned to the UI after connect.
type ConnectResultDTO struct {
	ConnectionID string `json:"connection_id"`
	ConfigID     string `json:"config_id"`
	Status       string `json:"status"`
	ConfPath     string `json:"conf_path"`
	DryRun       bool   `json:"dry_run"`
}

// Connect provisions and starts (or dry-runs) the tunnel.
func (a *App) Connect() (ConnectResultDTO, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return ConnectResultDTO{}, err
	}
	res, err := core.Connect(context.Background())
	if err != nil {
		return ConnectResultDTO{}, err
	}
	return toDTO(res, a.opts.DryRun), nil
}

// Disconnect stops the tunnel and revokes the CP allocation.
func (a *App) Disconnect() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return err
	}
	return core.Disconnect(context.Background())
}

func toDTO(res config.ConnectResult, dry bool) ConnectResultDTO {
	return ConnectResultDTO{
		ConnectionID: res.ConnectionID,
		ConfigID:     res.ConfigID,
		Status:       res.Status,
		ConfPath:     res.Assembled.ConfPath,
		DryRun:       dry,
	}
}

// DefaultDataDir returns ~/.config/focusvpn.
func DefaultDataDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".config", "focusvpn")
}
