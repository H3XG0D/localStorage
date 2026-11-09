package xrayapplier

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// CLI talks to a local Xray process through `xray api`.
type CLI struct {
	Bin string // default "xray"
	API string // host:port, e.g. 127.0.0.1:10085
}

func (c CLI) bin() string {
	if c.Bin != "" {
		return c.Bin
	}
	return "xray"
}

func (c CLI) run(ctx context.Context, args ...string) ([]byte, error) {
	// -s goes before positional arguments: `xray api adu` stops flag parsing
	// at the JSON file name.
	full := []string{"api", args[0], "-s", c.API}
	full = append(full, args[1:]...)
	cmd := exec.CommandContext(ctx, c.bin(), full...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = strings.TrimSpace(stdout.String())
		}
		return nil, fmt.Errorf("xray api %s: %w: %s", args[0], err, msg)
	}
	return stdout.Bytes(), nil
}

func (c CLI) ListUsers(ctx context.Context, tag string) ([]User, error) {
	out, err := c.run(ctx, "inbounduser", "-tag="+tag)
	if err != nil {
		return nil, err
	}
	return parseUsers(out)
}

func (c CLI) AddUser(ctx context.Context, tag Tag, email, id string) error {
	doc := map[string]any{
		"inbounds": []any{map[string]any{
			"tag": tag.Name, "listen": "127.0.0.1", "port": tag.Port, "protocol": "vless",
			"settings": map[string]any{
				"decryption": "none",
				"clients":    []any{map[string]any{"id": id, "email": email, "level": 0}},
			},
		}},
	}
	f, err := os.CreateTemp("", "focusvpn-xray-user-*.json")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	enc := json.NewEncoder(f)
	if err := enc.Encode(doc); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	out, err := c.run(ctx, "adu", name)
	if err != nil {
		return err
	}
	// xray exits 0 even when the user was rejected; the summary line is the signal.
	if strings.Contains(string(out), "Added 0") {
		return fmt.Errorf("xray api adu: %s", strings.TrimSpace(string(out)))
	}
	return nil
}

func (c CLI) RemoveUser(ctx context.Context, tag, email string) error {
	_, err := c.run(ctx, "rmu", "-tag="+tag, email)
	return err
}

func (c CLI) OnlineCount(ctx context.Context) (int, error) {
	out, err := c.run(ctx, "statsgetallonlineusers")
	if err != nil {
		return 0, err
	}
	return parseOnline(out)
}

// Ping checks that the Xray API answers. A refused connection means the process is down.
func (c CLI) Ping(ctx context.Context) error {
	_, err := c.run(ctx, "statssys")
	return err
}

// UserIPs returns the live source addresses of each online user email.
// Xray 26.3.27 has no "all users" IP call, so each online email is queried.
func (c CLI) UserIPs(ctx context.Context) (map[string][]string, error) {
	out, err := c.run(ctx, "statsgetallonlineusers")
	if err != nil {
		return nil, err
	}
	emails, err := parseOnlineEmails(out)
	if err != nil {
		return nil, err
	}
	type item struct {
		email string
		ips   []string
		err   error
	}
	ch := make(chan item, len(emails))
	sem := make(chan struct{}, 8)
	for _, email := range emails {
		sem <- struct{}{}
		go func(email string) {
			defer func() { <-sem }()
			raw, err := c.run(ctx, "statsonlineiplist", "-email="+email)
			if err != nil {
				ch <- item{email: email, err: err}
				return
			}
			ips, err := parseOnlineIPList(raw)
			ch <- item{email: email, ips: ips, err: err}
		}(email)
	}
	result := map[string][]string{}
	var first error
	for range emails {
		it := <-ch
		if it.err != nil {
			if first == nil {
				first = it.err
			}
			continue
		}
		result[it.email] = it.ips
	}
	if len(result) == 0 && first != nil {
		return nil, first
	}
	return result, nil
}

func (c CLI) Traffic(ctx context.Context) (int64, int64, error) {
	// User counters move; the inbound counters on Xray 26 stay at zero, so the
	// panel's "traffic today" would too if we summed those.
	out, err := c.run(ctx, "statsquery", "-pattern", "user>>>")
	if err != nil {
		return 0, 0, err
	}
	return parseTraffic(out)
}

func parseUsers(raw []byte) ([]User, error) {
	var env struct {
		Users []struct {
			Email   string `json:"email"`
			Account struct {
				ID string `json:"id"`
			} `json:"account"`
		} `json:"users"`
	}
	if len(bytes.TrimSpace(raw)) == 0 {
		return nil, nil
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return nil, fmt.Errorf("xray users: %w", err)
	}
	out := make([]User, 0, len(env.Users))
	for _, u := range env.Users {
		if u.Email != "" {
			out = append(out, User{Email: u.Email, UUID: u.Account.ID})
		}
	}
	return out, nil
}

func parseOnline(raw []byte) (int, error) {
	emails, err := parseOnlineEmails(raw)
	return len(emails), err
}

func parseOnlineEmails(raw []byte) ([]string, error) {
	var env struct {
		Users json.RawMessage `json:"users"`
	}
	if len(bytes.TrimSpace(raw)) == 0 || string(bytes.TrimSpace(raw)) == "{}" {
		return nil, nil
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return nil, fmt.Errorf("xray online: %w", err)
	}
	if len(env.Users) == 0 || string(env.Users) == "null" {
		return nil, nil
	}
	var emails []string
	if err := json.Unmarshal(env.Users, &emails); err == nil {
		return unique(emails), nil
	}
	var objs []struct {
		Email string `json:"email"`
	}
	if err := json.Unmarshal(env.Users, &objs); err != nil {
		return nil, fmt.Errorf("xray online: %w", err)
	}
	emails = emails[:0]
	for _, o := range objs {
		emails = append(emails, o.Email)
	}
	return unique(emails), nil
}

func parseOnlineIPList(raw []byte) ([]string, error) {
	var env struct {
		IPs map[string]json.RawMessage `json:"ips"`
	}
	if len(bytes.TrimSpace(raw)) == 0 || string(bytes.TrimSpace(raw)) == "{}" {
		return nil, nil
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return nil, fmt.Errorf("xray ips: %w", err)
	}
	out := make([]string, 0, len(env.IPs))
	for ip := range env.IPs {
		if ip != "" {
			out = append(out, ip)
		}
	}
	return out, nil
}

func parseTraffic(raw []byte) (downlink, uplink int64, err error) {
	var env struct {
		Stat []struct {
			Name  string `json:"name"`
			Value int64  `json:"value"`
		} `json:"stat"`
	}
	if len(bytes.TrimSpace(raw)) == 0 || string(bytes.TrimSpace(raw)) == "{}" {
		return 0, 0, nil
	}
	if err = json.Unmarshal(raw, &env); err != nil {
		return 0, 0, fmt.Errorf("xray traffic: %w", err)
	}
	for _, s := range env.Stat {
		switch {
		case strings.HasSuffix(s.Name, ">>>downlink"):
			downlink += s.Value
		case strings.HasSuffix(s.Name, ">>>uplink"):
			uplink += s.Value
		}
	}
	return downlink, uplink, nil
}

func unique(in []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range in {
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}
