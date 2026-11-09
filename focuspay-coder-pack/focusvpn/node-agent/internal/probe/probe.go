// Package probe checks whether a traffic node can actually carry VPN sessions.
// The first failing check becomes the reason the control plane stores.
package probe

import (
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"
)

const certWarn = 48 * time.Hour

// Result is one pass over the node. Degraded still serves users.
type Result struct {
	OK       bool
	Degraded bool
	Reason   string
}

// Checks are the steps, in order. Nil steps are skipped (unit tests).
type Checks struct {
	Xray   func(ctx context.Context) error
	TLS    func(ctx context.Context) (expires time.Time, err error)
	Decoy  func(ctx context.Context) error
	Egress func(ctx context.Context) error
	Now    func() time.Time
}

// Run returns the first hard failure, or a certificate warning when the rest pass.
func (c Checks) Run(ctx context.Context) Result {
	now := time.Now()
	if c.Now != nil {
		now = c.Now()
	}
	if c.Xray != nil {
		if err := c.Xray(ctx); err != nil {
			return Result{Reason: "Xray не отвечает: " + oneLine(err)}
		}
	}
	var expires time.Time
	if c.TLS != nil {
		exp, err := c.TLS(ctx)
		if err != nil {
			return Result{Reason: "TLS на 443 не поднимается: " + oneLine(err)}
		}
		expires = exp
	}
	if c.Decoy != nil {
		if err := c.Decoy(ctx); err != nil {
			return Result{Reason: "сайт-заглушка не отвечает: " + oneLine(err)}
		}
	}
	if c.Egress != nil {
		if err := c.Egress(ctx); err != nil {
			return Result{Reason: "с ноды нет выхода в интернет: " + oneLine(err)}
		}
	}
	if !expires.IsZero() && expires.Sub(now) < certWarn {
		return Result{OK: true, Degraded: true, Reason: "сертификат истекает " + expires.UTC().Format("02.01.2006 15:04") + " UTC"}
	}
	return Result{OK: true}
}

func oneLine(err error) string {
	s := err.Error()
	if len(s) > 180 {
		s = s[:180]
	}
	return s
}

// Live builds the checks a node agent runs against itself.
func Live(xray func(ctx context.Context) error, serverName string) Checks {
	return Checks{
		Xray: xray,
		TLS: func(ctx context.Context) (time.Time, error) {
			if serverName == "" {
				return time.Time{}, fmt.Errorf("не задан AGENT_PUBLIC_HOST")
			}
			d := &tls.Dialer{
				NetDialer: &net.Dialer{Timeout: 3 * time.Second},
				Config:    &tls.Config{ServerName: serverName, MinVersion: tls.VersionTLS12},
			}
			conn, err := d.DialContext(ctx, "tcp", "127.0.0.1:443")
			if err != nil {
				return time.Time{}, err
			}
			defer conn.Close()
			cs := conn.(*tls.Conn).ConnectionState()
			if len(cs.PeerCertificates) == 0 {
				return time.Time{}, fmt.Errorf("сертификат не представлен")
			}
			return cs.PeerCertificates[0].NotAfter, nil
		},
		Decoy: func(ctx context.Context) error {
			ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
			defer cancel()
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://127.0.0.1:8080/", nil)
			if err != nil {
				return err
			}
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				return err
			}
			defer resp.Body.Close()
			_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1024))
			if resp.StatusCode != http.StatusOK {
				return fmt.Errorf("HTTP %d", resp.StatusCode)
			}
			return nil
		},
		Egress: func(ctx context.Context) error {
			d := net.Dialer{Timeout: 3 * time.Second}
			conn, err := d.DialContext(ctx, "tcp", "1.1.1.1:443")
			if err != nil {
				return err
			}
			return conn.Close()
		},
	}
}
