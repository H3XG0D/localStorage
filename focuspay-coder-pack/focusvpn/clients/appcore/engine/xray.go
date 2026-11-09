package engine

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"

	appruntime "focusvpn.example/focusvpn/clients/appcore/runtime"
	"focusvpn.example/focusvpn/clients/shared/xray"
)

// XrayEngine runs VLESS+REALITY via an external Xray-core binary (MPL-2.0).
// We do not link or modify Xray sources — JSON config only (ADR-002 / OPEN_SOURCE).
// dryRun: write+validate JSON, no process. Real: `xray run -c <json>` (or XRAY_BIN).
type XrayEngine struct {
	mu       sync.Mutex
	state    State
	dryRun   bool
	cmd      *exec.Cmd
	proc     *appruntime.Process
	confPath string
	elevate  bool
	Bin      string // optional override; default env XRAY_BIN or "xray"
}

// NewXray constructs the Xray subprocess engine.
func NewXray(dryRun bool) *XrayEngine {
	return &XrayEngine{state: StateDisconnected, dryRun: dryRun}
}

// SetElevate makes the next Start ask for administrator rights (pkexec or UAC).
func (e *XrayEngine) SetElevate(v bool) {
	e.mu.Lock()
	e.elevate = v
	e.mu.Unlock()
}

// Prepare checks the binary exists unless dry-run.
func (e *XrayEngine) Prepare(_ context.Context) error {
	if e.dryRun {
		return nil
	}
	bin := e.bin()
	if _, err := exec.LookPath(bin); err != nil {
		return fmt.Errorf("не найден xray — в окне приложения нажмите «Скачать»")
	}
	return nil
}

// Start writes/uses JSON at cfg.ConfPath (or builds from cfg.Xray) and optionally starts xray.
func (e *XrayEngine) Start(ctx context.Context, cfg AssembledConfig) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	_ = e.stopLocked()
	e.state = StateConnecting

	path := cfg.ConfPath
	if cfg.Xray != nil {
		dir := cfg.ConfDir
		if dir == "" {
			dir = os.TempDir()
		}
		p, err := xray.WriteJSON(dir, "xray-client.json", *cfg.Xray)
		if err != nil {
			e.state = StateError
			return err
		}
		path = p
	}
	if path == "" {
		e.state = StateError
		return fmt.Errorf("engine/xray: ConfPath or Xray config required")
	}
	e.confPath = path

	raw, err := os.ReadFile(path)
	if err != nil {
		e.state = StateError
		return err
	}
	var doc xray.Document
	if err := json.Unmarshal(raw, &doc); err != nil {
		e.state = StateError
		return fmt.Errorf("engine/xray: invalid json: %w", err)
	}
	if err := xray.ValidateDocument(doc); err != nil {
		e.state = StateError
		return err
	}

	if e.dryRun {
		e.state = StateConnected
		return nil
	}

	elevate := e.elevate
	if !elevate {
		if err := appruntime.TunAccess(); err != nil {
			e.state = StateError
			return err
		}
	}
	var stderr bytes.Buffer
	e.mu.Unlock()
	proc, err := appruntime.StartProcess(ctx, elevate, e.bin(), path, &stderr)
	e.mu.Lock()
	if err != nil {
		e.state = StateError
		return err
	}
	e.proc = proc
	if proc.Cmd != nil {
		e.cmd = proc.Cmd
	}
	if early := e.track(proc, &stderr, elevate); early != nil {
		e.proc = nil
		e.cmd = nil
		e.state = StateError
		return early
	}
	e.state = StateConnected
	return nil
}

// track reaps the child. A fast exit becomes an error; a live process is watched
// until it ends. The caller holds e.mu except while this waits.
func (e *XrayEngine) track(proc *appruntime.Process, stderr *bytes.Buffer, elevate bool) error {
	if proc == nil || proc.Cmd == nil {
		return nil
	}
	done := make(chan error, 1)
	go func() { done <- proc.Cmd.Wait() }()
	if !elevate {
		e.mu.Unlock()
		var early error
		select {
		case err := <-done:
			if err == nil {
				err = errors.New("процесс сразу завершился")
			}
			early = classifyStart(stderr.String(), err)
		case <-time.After(700 * time.Millisecond):
		}
		e.mu.Lock()
		if early != nil {
			return early
		}
	}
	go func() {
		err := <-done
		e.mu.Lock()
		if e.proc == proc {
			e.proc = nil
			e.cmd = nil
			e.state = StateDisconnected
		}
		e.mu.Unlock()
		_ = err
	}()
	return nil
}

func classifyStart(stderr string, err error) error {
	text := strings.ToLower(stderr + " " + err.Error())
	if strings.Contains(text, "permission") || strings.Contains(text, "not permitted") || strings.Contains(text, "access is denied") || strings.Contains(text, "administrator") {
		return appruntime.ErrNeedAdmin
	}
	msg := strings.TrimSpace(stderr)
	if msg == "" {
		msg = err.Error()
	}
	return fmt.Errorf("xray не запустился: %s", msg)
}

// Stop terminates the xray process if running.
func (e *XrayEngine) Stop(_ context.Context) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.stopLocked()
}

func (e *XrayEngine) stopLocked() error {
	if e.proc != nil {
		e.proc.Kill()
		e.proc = nil
		e.cmd = nil
	}
	e.state = StateDisconnected
	return nil
}

// State returns lifecycle state.
func (e *XrayEngine) State() State {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.state
}

// Stats is empty until xray stats API is wired.
func (e *XrayEngine) Stats() (Stats, error) { return Stats{}, nil }

func (e *XrayEngine) bin() string {
	if e.Bin != "" {
		return e.Bin
	}
	if v := os.Getenv("XRAY_BIN"); v != "" {
		return v
	}
	return "xray"
}

var _ VPNEngine = (*XrayEngine)(nil)
