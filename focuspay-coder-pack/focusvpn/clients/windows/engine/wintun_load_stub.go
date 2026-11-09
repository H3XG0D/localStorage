//go:build !windows

package engine

import "fmt"

func probeWintun(dllName string) (string, error) {
	if dllName == "" {
		dllName = "wintun.dll"
	}
	return fmt.Sprintf("unsupported-os:%s", dllName), fmt.Errorf("wintun: LoadLibraryEx only available on Windows (use dry-run)")
}
