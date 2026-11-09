//go:build !windows

package storage

// protect is a no-op envelope on non-Windows (CI / cross-dev). File mode 0600 remains.
func protect(plain []byte) ([]byte, error) {
	out := make([]byte, 0, len(blobPrefix)+len(plain))
	out = append(out, blobPrefix...)
	out = append(out, plain...)
	return out, nil
}

func unprotect(blob []byte) ([]byte, error) {
	if len(blob) >= len(blobPrefix) && string(blob[:len(blobPrefix)]) == blobPrefix {
		return blob[len(blobPrefix):], nil
	}
	return blob, nil
}
