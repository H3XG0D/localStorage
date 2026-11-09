package app

import (
	"context"

	appclient "focusvpn.example/focusvpn/clients/appcore/client"
	"focusvpn.example/focusvpn/clients/appcore/engine"
	appruntime "focusvpn.example/focusvpn/clients/appcore/runtime"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// TelegramStartDTO is the deep link and the token the UI polls.
type TelegramStartDTO struct {
	DeepLink  string `json:"deep_link"`
	WaitToken string `json:"wait_token"`
	ExpiresIn int    `json:"expires_in"`
}

// TelegramWaitDTO is ready once the user confirms in Telegram.
type TelegramWaitDTO struct {
	Ready bool `json:"ready"`
}

// AccountDTO is the account screen.
type AccountDTO struct {
	Email       string               `json:"email,omitempty"`
	Plan        string               `json:"plan,omitempty"`
	Status      string               `json:"status,omitempty"`
	EndsAt      string               `json:"ends_at,omitempty"`
	MaxDevices  int                  `json:"max_devices,omitempty"`
	DevicesUsed int                  `json:"devices_used,omitempty"`
	Devices     []apitypes.DeviceDTO `json:"devices,omitempty"`
}

// LinkDTO is tunnel throughput. OK is false until two samples exist.
type LinkDTO struct {
	DownMbps float64 `json:"down_mbps"`
	UpMbps   float64 `json:"up_mbps"`
	OK       bool    `json:"ok"`
}

// TelegramStart begins a deep-link login.
func (a *App) TelegramStart() (TelegramStartDTO, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return TelegramStartDTO{}, err
	}
	start, err := core.StartTelegram(context.Background())
	if err != nil {
		return TelegramStartDTO{}, err
	}
	return TelegramStartDTO{DeepLink: start.DeepLink, WaitToken: start.WaitToken, ExpiresIn: start.ExpiresIn}, nil
}

// TelegramWait polls until the Telegram confirmation lands.
func (a *App) TelegramWait(waitToken string) (TelegramWaitDTO, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return TelegramWaitDTO{}, err
	}
	ready, err := core.WaitTelegram(context.Background(), waitToken)
	return TelegramWaitDTO{Ready: ready}, err
}

// LoginCode redeems a bot access code.
func (a *App) LoginCode(code string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return err
	}
	return core.LoginWithCode(context.Background(), code)
}

// Account returns subscription and devices.
func (a *App) Account() (AccountDTO, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	core, err := a.openLocked()
	if err != nil {
		return AccountDTO{}, err
	}
	view, err := core.Account(context.Background())
	if err != nil {
		return AccountDTO{}, err
	}
	return accountDTO(view), nil
}

// Ping is a TCP handshake to host:port, or -1.
func (a *App) Ping(host string, port int) int {
	return appclient.TcpPing(host, port)
}

// Runtime reports Xray (and, on Windows, the adapter) and whether an admin prompt is required.
func (a *App) Runtime() (appruntime.Report, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if _, err := a.openLocked(); err != nil {
		return appruntime.Report{}, err
	}
	return appruntime.Inspect(a.opts.DataDir), nil
}

// InstallRuntime downloads the official Xray release into the profile directory.
func (a *App) InstallRuntime() (appruntime.Report, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if _, err := a.openLocked(); err != nil {
		return appruntime.Report{}, err
	}
	return appruntime.Install(context.Background(), a.opts.DataDir)
}

// AllowAdmin makes the next connect ask the system for administrator rights.
func (a *App) AllowAdmin() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.xray == nil {
		if _, err := a.openLocked(); err != nil {
			return err
		}
	}
	if a.xray != nil {
		a.xray.SetElevate(true)
	}
	return nil
}

// Tunnel is the engine state without a control-plane round trip.
func (a *App) Tunnel() string {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.core == nil {
		return "disconnected"
	}
	return a.core.EngineState()
}

// Link samples xray0 counters.
func (a *App) Link() LinkDTO {
	down, up, ok := engine.SampleMbps(engineTunName)
	return LinkDTO{DownMbps: down, UpMbps: up, OK: ok}
}

const engineTunName = "xray0"

func accountDTO(view appclient.AccountView) AccountDTO {
	return AccountDTO{
		Email:       view.Email,
		Plan:        view.Plan,
		Status:      view.Status,
		EndsAt:      view.EndsAt,
		MaxDevices:  view.MaxDevices,
		DevicesUsed: view.DevicesUsed,
		Devices:     view.Devices,
	}
}
