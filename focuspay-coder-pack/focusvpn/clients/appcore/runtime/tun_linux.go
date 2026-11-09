//go:build linux

package runtime

import (
	"errors"
	"os"
	"syscall"
)

// TunAccess reports whether this process may open the tunnel device.
func TunAccess() error {
	f, err := os.OpenFile("/dev/net/tun", os.O_RDWR, 0)
	if err == nil {
		_ = f.Close()
		return nil
	}
	if os.IsNotExist(err) {
		return errors.New("в системе нет /dev/net/tun")
	}
	if errors.Is(err, syscall.EPERM) || errors.Is(err, syscall.EACCES) || os.IsPermission(err) {
		return ErrNeedAdmin
	}
	return err
}
