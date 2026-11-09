// Command migrate applies FocusVPN database migrations (golang-migrate, embedded).
//
// Usage:
//
//	migrate -url postgres://user:pass@host:5432/db?sslmode=disable up
//	migrate -url ... down
//	migrate -url ... version
package main

import (
	"flag"
	"fmt"
	"log"
	"os"

	"focusvpn.example/focusvpn/backend/internal/platform/migrate"
)

func main() {
	url := flag.String("url", os.Getenv("FOCUSVPN_DATABASE_URL"), "PostgreSQL URL (or FOCUSVPN_DATABASE_URL)")
	flag.Parse()

	cmd := flag.Arg(0)
	if *url == "" {
		log.Fatal("missing -url (or FOCUSVPN_DATABASE_URL)")
	}

	switch cmd {
	case "up", "":
		if err := migrate.Up(*url); err != nil {
			log.Fatalf("migrate up: %v", err)
		}
		fmt.Println("migrations applied (up)")
	case "down":
		if err := migrate.Down(*url); err != nil {
			log.Fatalf("migrate down: %v", err)
		}
		fmt.Println("migrations reverted (down)")
	case "version":
		v, dirty, err := migrate.Version(*url)
		if err != nil {
			log.Fatalf("migrate version: %v", err)
		}
		fmt.Printf("version=%d dirty=%v\n", v, dirty)
	default:
		log.Fatalf("unknown command %q (want: up|down|version)", cmd)
	}
}
