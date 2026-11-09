//go:build !windows

package runtime

import (
	"context"
	"fmt"
	"io"
	"os/exec"
	"syscall"
)

// Process is a running xray, either a child or an elevated pid.
type Process struct {
	Cmd *exec.Cmd
	PID int
}

// StartProcess launches xray. elevate asks the desktop session for administrator
// rights through pkexec instead of failing closed.
func StartProcess(ctx context.Context, elevate bool, bin, config string, stderr io.Writer) (*Process, error) {
	argv := []string{bin, "run", "-c", config}
	if elevate {
		if _, err := exec.LookPath("pkexec"); err != nil {
			return nil, fmt.Errorf("нужны права администратора, а pkexec не установлен")
		}
		argv = append([]string{"pkexec"}, argv...)
	}
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Stdout = stderr
	cmd.Stderr = stderr
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	return &Process{Cmd: cmd, PID: cmd.Process.Pid}, nil
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
		_ = syscall.Kill(p.PID, syscall.SIGKILL)
	}
}
