//go:build wails

// Command focusvpn-gui is the FocusPay-styled Wails desktop client.
// Build: go build -tags wails -o bin/focusvpn-gui ./clients/desktop/cmd/focusvpn-gui
// Requires Linux webkit2gtk (libwebkit2gtk-4.1-dev) + GTK.
package main

import (
	"flag"
	"log"
	"os"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"

	desktop "focusvpn.example/focusvpn/clients/desktop/app"
	"focusvpn.example/focusvpn/clients/desktop/frontend"
)

func main() {
	api := flag.String("api", envOr("FOCUSVPN_API", "https://focuspay.org/vpn-api"), "control plane URL")
	dataDir := flag.String("data-dir", "", "session dir (default ~/.config/focusvpn)")
	dryRun := flag.Bool("dry-run", envOr("FOCUSVPN_DRY_RUN", "") == "1", "write the xray config without starting it")
	flag.Parse()

	app := desktop.New(desktop.Options{
		APIBase: *api,
		DataDir: *dataDir,
		DryRun:  *dryRun,
		Engine:  "xray",
	})

	err := wails.Run(&options.App{
		Title:  "FocusVPN",
		Width:  420,
		Height: 780,
		AssetServer: &assetserver.Options{
			Assets: frontend.FS,
		},
		BackgroundColour: &options.RGBA{R: 10, G: 10, B: 14, A: 255},
		Bind: []interface{}{
			app,
		},
	})
	if err != nil {
		log.Fatal(err)
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
