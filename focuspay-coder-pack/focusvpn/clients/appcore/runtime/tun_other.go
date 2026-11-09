//go:build !linux

package runtime

// TunAccess on Windows is decided when Xray actually starts the adapter.
func TunAccess() error { return nil }
