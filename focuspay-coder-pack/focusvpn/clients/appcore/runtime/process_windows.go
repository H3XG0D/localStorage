//go:build windows

package runtime

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
)

// Process is a running xray, either a child or an elevated pid.
type Process struct {
	Cmd *exec.Cmd
	PID int
}

// StartProcess launches xray. elevate shows the Windows administrator prompt.
func StartProcess(ctx context.Context, elevate bool, bin, config string, stderr io.Writer) (*Process, error) {
	if !elevate {
		cmd := exec.CommandContext(ctx, bin, "run", "-c", config)
		cmd.Stdout = stderr
		cmd.Stderr = stderr
		if err := cmd.Start(); err != nil {
			return nil, err
		}
		return &Process{Cmd: cmd, PID: cmd.Process.Pid}, nil
	}
	script := `$p = Start-Process -FilePath $env:FOCUSVPN_XRAY -ArgumentList @('run','-c',$env:FOCUSVPN_XRAY_CFG) -Verb RunAs -WindowStyle Hidden -PassThru; if (-not $p) { exit 1 }; Write-Output $p.Id`
	cmd := exec.CommandContext(ctx, "powershell", "-NoProfile", "-Command", script)
	cmd.Env = append(os.Environ(), "FOCUSVPN_XRAY="+bin, "FOCUSVPN_XRAY_CFG="+config)
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("нужны права администратора: %w", err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(out)))
	if err != nil || pid <= 0 {
		return nil, fmt.Errorf("не удалось запустить Xray от администратора")
	}
	return &Process{PID: pid}, nil
}

// Kill stops the process.
func (p *Process) Kill() {
	if p == nil {
		return
	}
	if p.Cmd != nil && p.Cmd.Process != nil {
		_ = p.Cmd.Process.Kill()
		return
	}
	if p.PID > 0 {
		_ = exec.Command("taskkill", "/PID", strconv.Itoa(p.PID), "/F").Run()
	}
}
