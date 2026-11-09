package runtime

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSHA256FromDgst(t *testing.T) {
	got, err := sha256FromDgst("MD5= aa\nSHA2-256= f851110beaff16e78d643f0ccfd9524b4a44dfd59bae3e34bb52bba378f7690e\n")
	if err != nil || !strings.HasPrefix(got, "f851110") {
		t.Fatalf("%s %v", got, err)
	}
	if _, err := sha256FromDgst("MD5= aa\n"); err == nil {
		t.Fatal("expected missing sha")
	}
}

func TestInstallUnpacksVerifiedZip(t *testing.T) {
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	w, err := zw.Create("xray")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write([]byte("not-a-real-binary")); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(buf.Bytes())
	dgst := "SHA2-256= " + hex.EncodeToString(sum[:]) + "\n"
	old := fetch
	prevBin := os.Getenv("XRAY_BIN")
	fetch = func(_ context.Context, url string) ([]byte, error) {
		if strings.HasSuffix(url, ".dgst") {
			return []byte(dgst), nil
		}
		return buf.Bytes(), nil
	}
	t.Cleanup(func() {
		fetch = old
		if prevBin == "" {
			_ = os.Unsetenv("XRAY_BIN")
		} else {
			_ = os.Setenv("XRAY_BIN", prevBin)
		}
	})

	dir := t.TempDir()
	rep, err := Install(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	if !rep.Ready && !rep.NeedAdmin {
		t.Fatalf("report %+v", rep)
	}
	body, err := os.ReadFile(filepath.Join(dir, "runtime", "xray"))
	if err != nil {
		t.Fatal(err)
	}
	if string(body) != "not-a-real-binary" {
		t.Fatalf("body %q", body)
	}
	if os.Getenv("XRAY_BIN") != filepath.Join(dir, "runtime", "xray") {
		t.Fatalf("XRAY_BIN %q", os.Getenv("XRAY_BIN"))
	}
}

func TestInstallRejectsBadChecksum(t *testing.T) {
	old := fetch
	fetch = func(_ context.Context, url string) ([]byte, error) {
		if strings.HasSuffix(url, ".dgst") {
			return []byte("SHA2-256= 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"), nil
		}
		return []byte("nope"), nil
	}
	t.Cleanup(func() { fetch = old })
	if _, err := Install(context.Background(), t.TempDir()); err == nil || !strings.Contains(err.Error(), "не сошлась") {
		t.Fatal(err)
	}
}
