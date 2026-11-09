// Package runtime fetches the external tunnel programs a desktop install needs.
// Xray-core is MPL-2.0 and is never linked: the official release zip is unpacked
// next to the profile and started as its own process. On Windows the same folder
// gets the prebuilt wintun.dll (WireGuard LLC Prebuilt Binaries License), which
// Xray loads beside its own exe.
package runtime

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

// XrayVersion is the official release the desktop clients download.
// Same generation as the Android libXray pin.
const XrayVersion = "v26.9.30"

const wintunZipSHA256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"
const wintunURL = "https://www.wintun.net/builds/wintun-0.14.1.zip"

// ErrNeedAdmin means creating the tunnel interface needs an administrator prompt.
var ErrNeedAdmin = errors.New("нужны права администратора, чтобы создать сетевой интерфейс")

// Component is one missing program the UI can offer to download.
type Component struct {
	ID     string `json:"id"`
	Title  string `json:"title"`
	Detail string `json:"detail"`
}

// Report is what the window shows before Connect.
type Report struct {
	Ready     bool        `json:"ready"`
	NeedAdmin bool        `json:"need_admin"`
	XrayPath  string      `json:"xray_path,omitempty"`
	Missing   []Component `json:"missing"`
}

// Inspect looks in dir/runtime and, on Linux, on PATH.
func Inspect(dir string) Report {
	bin := bundledBinary(dir)
	if bin == "" && runtime.GOOS != "windows" {
		if p, err := exec.LookPath("xray"); err == nil {
			bin = p
		}
	}
	var missing []Component
	if bin == "" {
		missing = append(missing, Component{
			ID:     "xray",
			Title:  "Xray",
			Detail: "Движок туннеля. Скачивается отдельно и не встраивается в приложение.",
		})
	}
	if runtime.GOOS == "windows" && !wintunBeside(bin, dir) {
		missing = append(missing, Component{
			ID:     "wintun",
			Title:  "сетевой адаптер Windows",
			Detail: "Файл wintun.dll кладётся рядом с Xray.",
		})
	}
	rep := Report{Ready: len(missing) == 0, XrayPath: bin, Missing: missing}
	if err := TunAccess(); errors.Is(err, ErrNeedAdmin) {
		rep.NeedAdmin = true
	}
	return rep
}

// Install downloads the official archives into dir/runtime and checks their checksums.
func Install(ctx context.Context, dir string) (Report, error) {
	dest := filepath.Join(dir, "runtime")
	if err := os.MkdirAll(dest, 0700); err != nil {
		return Report{}, err
	}
	zipName, binName, err := assetNames()
	if err != nil {
		return Report{}, err
	}
	body, err := downloadVerified(ctx, releaseURL(zipName), releaseURL(zipName+".dgst"))
	if err != nil {
		return Report{}, err
	}
	if err := unpack(body, dest, map[string]string{binName: binName, "wintun.dll": "wintun.dll"}); err != nil {
		return Report{}, err
	}
	binPath := filepath.Join(dest, binName)
	if st, err := os.Stat(binPath); err != nil || st.IsDir() {
		return Report{}, fmt.Errorf("в архиве Xray нет %s", binName)
	}
	if runtime.GOOS != "windows" {
		if err := os.Chmod(binPath, 0755); err != nil {
			return Report{}, err
		}
	}
	if runtime.GOOS == "windows" {
		dll := filepath.Join(dest, "wintun.dll")
		if _, err := os.Stat(dll); err != nil {
			if err := installWintun(ctx, dest); err != nil {
				return Report{}, err
			}
		}
	}
	_ = os.Setenv("XRAY_BIN", binPath)
	return Inspect(dir), nil
}

func bundledBinary(dir string) string {
	name := "xray"
	if runtime.GOOS == "windows" {
		name = "xray.exe"
	}
	p := filepath.Join(dir, "runtime", name)
	st, err := os.Stat(p)
	if err != nil || st.IsDir() {
		return ""
	}
	return p
}

func wintunBeside(bin, dir string) bool {
	if bin != "" {
		if st, err := os.Stat(filepath.Join(filepath.Dir(bin), "wintun.dll")); err == nil && !st.IsDir() {
			return true
		}
	}
	st, err := os.Stat(filepath.Join(dir, "runtime", "wintun.dll"))
	return err == nil && !st.IsDir()
}

func assetNames() (zipName, binName string, err error) {
	switch runtime.GOOS {
	case "linux":
		binName = "xray"
		switch runtime.GOARCH {
		case "amd64":
			zipName = "Xray-linux-64.zip"
		case "arm64":
			zipName = "Xray-linux-arm64-v8a.zip"
		case "386":
			zipName = "Xray-linux-32.zip"
		default:
			err = fmt.Errorf("архитектура %s не поддерживается", runtime.GOARCH)
		}
	case "windows":
		binName = "xray.exe"
		switch runtime.GOARCH {
		case "amd64":
			zipName = "Xray-windows-64.zip"
		case "arm64":
			zipName = "Xray-windows-arm64-v8a.zip"
		case "386":
			zipName = "Xray-windows-32.zip"
		default:
			err = fmt.Errorf("архитектура %s не поддерживается", runtime.GOARCH)
		}
	default:
		err = fmt.Errorf("система %s не поддерживается", runtime.GOOS)
	}
	return zipName, binName, err
}

func releaseURL(name string) string {
	return "https://github.com/XTLS/Xray-core/releases/download/" + XrayVersion + "/" + name
}

func downloadVerified(ctx context.Context, zipURL, dgstURL string) ([]byte, error) {
	body, err := fetch(ctx, zipURL)
	if err != nil {
		return nil, fmt.Errorf("не удалось скачать Xray: %w", err)
	}
	dgst, err := fetch(ctx, dgstURL)
	if err != nil {
		return nil, fmt.Errorf("не удалось скачать контрольную сумму Xray: %w", err)
	}
	want, err := sha256FromDgst(string(dgst))
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(body)
	if !strings.EqualFold(hex.EncodeToString(sum[:]), want) {
		return nil, errors.New("контрольная сумма Xray не сошлась, файл не сохранён")
	}
	return body, nil
}

func sha256FromDgst(text string) (string, error) {
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "SHA2-256=") {
			sum := strings.TrimSpace(strings.TrimPrefix(line, "SHA2-256="))
			if len(sum) != 64 {
				return "", errors.New("контрольная сумма Xray повреждена")
			}
			return sum, nil
		}
	}
	return "", errors.New("в контрольной сумме Xray нет SHA2-256")
}

func installWintun(ctx context.Context, dest string) error {
	body, err := fetch(ctx, wintunURL)
	if err != nil {
		return fmt.Errorf("не удалось скачать сетевой адаптер: %w", err)
	}
	sum := sha256.Sum256(body)
	if hex.EncodeToString(sum[:]) != wintunZipSHA256 {
		return errors.New("контрольная сумма сетевого адаптера не сошлась, файл не сохранён")
	}
	arch := "amd64"
	switch runtime.GOARCH {
	case "arm64":
		arch = "arm64"
	case "386":
		arch = "x86"
	}
	want := "wintun/bin/" + arch + "/wintun.dll"
	zr, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
	if err != nil {
		return err
	}
	for _, f := range zr.File {
		if filepath.ToSlash(f.Name) != want {
			continue
		}
		return writeZipFile(f, filepath.Join(dest, "wintun.dll"), 0644)
	}
	return errors.New("в архиве адаптера нет wintun.dll")
}

func unpack(body []byte, dest string, names map[string]string) error {
	zr, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
	if err != nil {
		return fmt.Errorf("архив Xray повреждён: %w", err)
	}
	for _, f := range zr.File {
		base := filepath.Base(f.Name)
		out, ok := names[base]
		if !ok || f.FileInfo().IsDir() {
			continue
		}
		mode := os.FileMode(0755)
		if base == "wintun.dll" {
			mode = 0644
		}
		if err := writeZipFile(f, filepath.Join(dest, out), mode); err != nil {
			return err
		}
	}
	return nil
}

func writeZipFile(f *zip.File, path string, mode os.FileMode) error {
	rc, err := f.Open()
	if err != nil {
		return err
	}
	defer rc.Close()
	tmp := path + ".part"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(out, rc)
	closeErr := out.Close()
	if copyErr != nil {
		_ = os.Remove(tmp)
		return copyErr
	}
	if closeErr != nil {
		_ = os.Remove(tmp)
		return closeErr
	}
	return os.Rename(tmp, path)
}
