//go:build windows

package engine

import (
	"fmt"

	"golang.org/x/sys/windows"
)

// probeWintun loads wintun.dll via LoadLibraryEx (dynamic only — no static link).
func probeWintun(dllName string) (string, error) {
	if dllName == "" {
		dllName = "wintun.dll"
	}
	mod, err := windows.LoadLibraryEx(dllName, 0, windows.LOAD_LIBRARY_SEARCH_APPLICATION_DIR|windows.LOAD_LIBRARY_SEARCH_SYSTEM32)
	if err != nil {
		mod, err = windows.LoadLibrary(dllName)
		if err != nil {
			return fmt.Sprintf("missing:%s", dllName), fmt.Errorf("wintun: LoadLibraryEx %s: %w (place prebuilt wintun.dll next to the EXE)", dllName, err)
		}
	}
	defer windows.FreeLibrary(mod)
	return fmt.Sprintf("loaded:%s", dllName), nil
}
