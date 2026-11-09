// Command focusvpn is the Phase 3 Linux product CLI (AppCore-backed).
// Phase 2 harness remains at clients/cli for smoke/auth tooling.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	appclient "focusvpn.example/focusvpn/clients/appcore/client"
	"focusvpn.example/focusvpn/clients/appcore/engine"
	"focusvpn.example/focusvpn/clients/appcore/storage"
)

// defaultAPIBase is overridden at link time for release builds:
//
//	-ldflags "-X main.defaultAPIBase=https://api.example.com"
var defaultAPIBase = "http://localhost:8080"

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	cmd := os.Args[1]
	args := os.Args[2:]
	var err error
	switch cmd {
	case "login":
		err = cmdLogin(args)
	case "register":
		err = cmdRegister(args)
	case "logout":
		err = cmdLogout(args)
	case "status":
		err = cmdStatus(args)
	case "connect":
		err = cmdConnect(args)
	case "disconnect":
		err = cmdDisconnect(args)
	case "help", "-h", "--help":
		usage()
		return
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n", cmd)
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `focusvpn — FocusVPN Linux client (Phase 3 AppCore)

Usage:
  focusvpn login      --api URL --email E --password P [--data-dir DIR]
  focusvpn register   --api URL --email E --password P [--data-dir DIR]
  focusvpn logout     [--data-dir DIR]
  focusvpn status     [--data-dir DIR]
  focusvpn connect    [--data-dir DIR] [--dry-run] [--conf-dir DIR]
  focusvpn disconnect [--data-dir DIR]
`)
}

func openApp(api, dataDir, confDir string, dryRun bool) (*appclient.App, error) {
	if api == "" {
		st, err := storage.NewFileStore(dataDir)
		if err != nil {
			return nil, err
		}
		if b, err := st.Get(storage.KeyAPIBase); err == nil {
			api = string(b)
		}
	}
	if api == "" {
		api = defaultAPIBase
	}
	st, err := storage.NewFileStore(dataDir)
	if err != nil {
		return nil, err
	}
	if confDir == "" {
		confDir = filepath.Join(st.Dir(), "conf")
	}
	eng := engine.NewDefault(dryRun)
	return appclient.New(appclient.Options{
		APIBase:  api,
		Store:    st,
		Engine:   eng,
		ConfDir:  confDir,
		DryRun:   dryRun,
		Interface: "focusvpn0",
	})
}

func cmdLogin(args []string) error {
	fs := flag.NewFlagSet("login", flag.ExitOnError)
	api := fs.String("api", defaultAPIBase, "control plane URL")
	email := fs.String("email", "", "email")
	password := fs.String("password", "", "password")
	dataDir := fs.String("data-dir", "", "session dir (default ~/.config/focusvpn)")
	_ = fs.Parse(args)
	app, err := openApp(*api, *dataDir, "", true)
	if err != nil {
		return err
	}
	if err := app.Login(context.Background(), *email, *password); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "logged_in"})
}

func cmdRegister(args []string) error {
	fs := flag.NewFlagSet("register", flag.ExitOnError)
	api := fs.String("api", defaultAPIBase, "control plane URL")
	email := fs.String("email", "", "email")
	password := fs.String("password", "", "password")
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	app, err := openApp(*api, *dataDir, "", true)
	if err != nil {
		return err
	}
	if err := app.Register(context.Background(), *email, *password); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "registered"})
}

func cmdLogout(args []string) error {
	fs := flag.NewFlagSet("logout", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	app, err := openApp("", *dataDir, "", true)
	if err != nil {
		return err
	}
	if err := app.Logout(context.Background()); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "logged_out"})
}

func cmdStatus(args []string) error {
	fs := flag.NewFlagSet("status", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	app, err := openApp("", *dataDir, "", true)
	if err != nil {
		return err
	}
	st := app.Status()
	return json.NewEncoder(os.Stdout).Encode(st)
}

func cmdConnect(args []string) error {
	fs := flag.NewFlagSet("connect", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	confDir := fs.String("conf-dir", "", "awg conf directory")
	dryRun := fs.Bool("dry-run", false, "write conf only; skip awg-quick")
	_ = fs.Parse(args)
	app, err := openApp("", *dataDir, *confDir, *dryRun)
	if err != nil {
		return err
	}
	res, err := app.Connect(context.Background())
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{
		"connection_id": res.ConnectionID,
		"config_id":     res.ConfigID,
		"status":        res.Status,
		"conf_path":     res.Assembled.ConfPath,
		"dry_run":       *dryRun,
	})
}

func cmdDisconnect(args []string) error {
	fs := flag.NewFlagSet("disconnect", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	app, err := openApp("", *dataDir, "", true)
	if err != nil {
		return err
	}
	if err := app.Disconnect(context.Background()); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "disconnected"})
}
