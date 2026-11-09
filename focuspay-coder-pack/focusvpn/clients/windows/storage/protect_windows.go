//go:build windows

package storage

import (
	"unsafe"

	"golang.org/x/sys/windows"
)

// protect encrypts with DPAPI (CryptProtectData, CurrentUser).
func protect(plain []byte) ([]byte, error) {
	if len(plain) == 0 {
		return append([]byte(blobPrefix), plain...), nil
	}
	in := windows.DataBlob{
		Size: uint32(len(plain)),
		Data: &plain[0],
	}
	var out windows.DataBlob
	err := windows.CryptProtectData(&in, nil, nil, 0, nil, windows.CRYPTPROTECT_UI_FORBIDDEN, &out)
	if err != nil {
		return nil, formatProtectError("CryptProtectData", err)
	}
	defer func() { _, _ = windows.LocalFree(windows.Handle(unsafe.Pointer(out.Data))) }()
	cipher := unsafe.Slice(out.Data, int(out.Size))
	buf := make([]byte, 0, len(blobPrefix)+len(cipher))
	buf = append(buf, blobPrefix...)
	buf = append(buf, cipher...)
	return buf, nil
}

func unprotect(blob []byte) ([]byte, error) {
	if len(blob) < len(blobPrefix) || string(blob[:len(blobPrefix)]) != blobPrefix {
		return blob, nil
	}
	cipher := blob[len(blobPrefix):]
	if len(cipher) == 0 {
		return cipher, nil
	}
	in := windows.DataBlob{
		Size: uint32(len(cipher)),
		Data: &cipher[0],
	}
	var out windows.DataBlob
	err := windows.CryptUnprotectData(&in, nil, nil, 0, nil, windows.CRYPTPROTECT_UI_FORBIDDEN, &out)
	if err != nil {
		return nil, formatProtectError("CryptUnprotectData", err)
	}
	defer func() { _, _ = windows.LocalFree(windows.Handle(unsafe.Pointer(out.Data))) }()
	plain := unsafe.Slice(out.Data, int(out.Size))
	cp := make([]byte, len(plain))
	copy(cp, plain)
	return cp, nil
}
