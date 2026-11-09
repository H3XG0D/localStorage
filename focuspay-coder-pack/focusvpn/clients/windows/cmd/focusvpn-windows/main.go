// Command focusvpn-windows is the headless Windows AppCore CLI (smoke-windows / CI).
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	winapp "focusvpn.example/focusvpn/clients/windows/app"
)

// defaultAPIBase overridden via -ldflags for release builds.
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
	case "servers":
		err = cmdServers(args)
	case "select":
		err = cmdSelect(args)
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
	fmt.Fprint(os.Stderr, `focusvpn-windows — FocusVPN Windows bindings (FocusPay UI + amneziawg-go/wintun)

Usage:
  focusvpn-windows login      --api URL --email E --password P [--data-dir DIR]
  focusvpn-windows register   --api URL --email E --password P [--data-dir DIR]
  focusvpn-windows logout     [--data-dir DIR]
  focusvpn-windows status     [--data-dir DIR]
  focusvpn-windows servers    [--data-dir DIR]
  focusvpn-windows select     --node NODE [--data-dir DIR]
  focusvpn-windows connect    [--data-dir DIR] [--dry-run] [--conf-dir DIR]
  focusvpn-windows disconnect [--data-dir DIR]
`)
}

func openApp(api, dataDir, confDir string, dryRun bool) *winapp.App {
	return winapp.New(winapp.Options{
		APIBase: api,
		DataDir: dataDir,
		ConfDir: confDir,
		DryRun:  dryRun,
	})
}

func cmdLogin(args []string) error {
	fs := flag.NewFlagSet("login", flag.ExitOnError)
	api := fs.String("api", defaultAPIBase, "control plane URL")
	email := fs.String("email", "", "email")
	password := fs.String("password", "", "password")
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	a := openApp(*api, *dataDir, "", true)
	if err := a.Login(*email, *password); err != nil {
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
	a := openApp(*api, *dataDir, "", true)
	if err := a.Register(*email, *password); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "registered"})
}

func cmdLogout(args []string) error {
	fs := flag.NewFlagSet("logout", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	if err := openApp("", *dataDir, "", true).Logout(); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "logged_out"})
}

func cmdStatus(args []string) error {
	fs := flag.NewFlagSet("status", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	return json.NewEncoder(os.Stdout).Encode(openApp("", *dataDir, "", true).Status())
}

func cmdServers(args []string) error {
	fs := flag.NewFlagSet("servers", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	res, err := openApp("", *dataDir, "", true).ListServers()
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(res)
}

func cmdSelect(args []string) error {
	fs := flag.NewFlagSet("select", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	node := fs.String("node", "", "node code e.g. DE-01")
	_ = fs.Parse(args)
	if err := openApp("", *dataDir, "", true).SelectNode(*node); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"selected_node": *node})
}

func cmdConnect(args []string) error {
	fs := flag.NewFlagSet("connect", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	confDir := fs.String("conf-dir", "", "conf directory")
	dryRun := fs.Bool("dry-run", false, "skip CreateTUN (ChannelTUN dry-run)")
	_ = fs.Parse(args)
	res, err := openApp("", *dataDir, *confDir, *dryRun).Connect()
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(res)
}

func cmdDisconnect(args []string) error {
	fs := flag.NewFlagSet("disconnect", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	if err := openApp("", *dataDir, "", true).Disconnect(); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "disconnected"})
}
