// Command focusvpn-desktop is the headless desktop AppCore CLI used by smoke-desktop
// and as the binding surface shared with the Wails GUI (focusvpn-gui).
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	desktop "focusvpn.example/focusvpn/clients/desktop/app"
)

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
	fmt.Fprint(os.Stderr, `focusvpn-desktop — FocusVPN desktop bindings (FocusPay-styled GUI companion)

Usage:
  focusvpn-desktop login      --api URL --email E --password P [--data-dir DIR]
  focusvpn-desktop register   --api URL --email E --password P [--data-dir DIR]
  focusvpn-desktop logout     [--data-dir DIR]
  focusvpn-desktop status     [--data-dir DIR]
  focusvpn-desktop servers    [--data-dir DIR]
  focusvpn-desktop select     --node NODE [--data-dir DIR]
  focusvpn-desktop connect    [--data-dir DIR] [--dry-run] [--conf-dir DIR]
  focusvpn-desktop disconnect [--data-dir DIR]
`)
}

func openApp(api, dataDir, confDir string, dryRun bool) *desktop.App {
	return desktop.New(desktop.Options{
		APIBase: api,
		DataDir: dataDir,
		ConfDir: confDir,
		DryRun:  dryRun,
	})
}

func cmdLogin(args []string) error {
	fs := flag.NewFlagSet("login", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane URL")
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
	api := fs.String("api", "http://localhost:8080", "control plane URL")
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
	a := openApp("", *dataDir, "", true)
	if err := a.Logout(); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "logged_out"})
}

func cmdStatus(args []string) error {
	fs := flag.NewFlagSet("status", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	a := openApp("", *dataDir, "", true)
	return json.NewEncoder(os.Stdout).Encode(a.Status())
}

func cmdServers(args []string) error {
	fs := flag.NewFlagSet("servers", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	a := openApp("", *dataDir, "", true)
	res, err := a.ListServers()
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
	a := openApp("", *dataDir, "", true)
	if err := a.SelectNode(*node); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"selected_node": *node})
}

func cmdConnect(args []string) error {
	fs := flag.NewFlagSet("connect", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	confDir := fs.String("conf-dir", "", "conf directory")
	dryRun := fs.Bool("dry-run", false, "write conf only")
	_ = fs.Parse(args)
	a := openApp("", *dataDir, *confDir, *dryRun)
	res, err := a.Connect()
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(res)
}

func cmdDisconnect(args []string) error {
	fs := flag.NewFlagSet("disconnect", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "session dir")
	_ = fs.Parse(args)
	a := openApp("", *dataDir, "", true)
	if err := a.Disconnect(); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": "disconnected"})
}
