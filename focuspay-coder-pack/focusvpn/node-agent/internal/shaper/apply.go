package shaper

import (
	"context"
	"fmt"
	"log"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

// ifaceName is conservative: tc interpolates the device into a command line.
var ifaceName = regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,15}$`)

// Exec runs one command. Tests substitute a recorder.
type Exec func(ctx context.Context, name string, args ...string) error

// ExecCommand runs a command and includes its output in the error.
func ExecCommand(ctx context.Context, name string, args ...string) error {
	cmd := exec.CommandContext(ctx, name, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		return fmt.Errorf("%s: %w: %s", name, err, msg)
	}
	return nil
}

// DefaultIface is the device used for the default IPv4 route.
func DefaultIface(ctx context.Context) (string, error) {
	cmd := exec.CommandContext(ctx, "ip", "-4", "route", "get", "1.1.1.1")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("ip route: %w: %s", err, strings.TrimSpace(string(out)))
	}
	f := strings.Fields(string(out))
	for i, tok := range f {
		if tok == "dev" && i+1 < len(f) && ifaceName.MatchString(f[i+1]) {
			return f[i+1], nil
		}
	}
	return "", fmt.Errorf("ip route: no device in %q", strings.TrimSpace(string(out)))
}

// Applier keeps one 100mbit HTB class per user on the egress device and on an
// IFB device that carries the same users' uploads.
type Applier struct {
	Exec  Exec
	Iface string
	IFB   string
	rate  string

	ready   bool
	ifbOK   bool
	classOf map[string]uint16
	filters map[string]uint32 // "e:ip" / "i:ip" -> tc handle
	nextH   uint32
}

// NewApplier shapes iface. ifb is the upload redirect device (for example ifb-fvpn).
func NewApplier(exec Exec, iface, ifb string, mbps int) *Applier {
	if mbps <= 0 {
		mbps = 100
	}
	if ifb == "" {
		ifb = "ifb-fvpn"
	}
	return &Applier{
		Exec:    exec,
		Iface:   iface,
		IFB:     ifb,
		rate:    strconv.Itoa(mbps) + "mbit",
		classOf: map[string]uint16{},
		filters: map[string]uint32{},
		nextH:   1,
	}
}

// Sync applies classes for shaped (email -> public IPs). An empty iface is a no-op.
func (a *Applier) Sync(ctx context.Context, shaped map[string][]string) error {
	if a == nil || a.Exec == nil || !ifaceName.MatchString(a.Iface) {
		return nil
	}
	if !a.ready {
		if err := a.setup(ctx); err != nil {
			return err
		}
		a.ready = true
	}
	classes, next := Assign(shaped, a.classOf)
	want := map[string]bool{}
	for _, c := range classes {
		a.ensureClass(ctx, a.Iface, c.Minor)
		if a.ifbOK {
			a.ensureClass(ctx, a.IFB, c.Minor)
		}
		for _, ip := range c.IPs {
			a.ensureFilter(ctx, "e", a.Iface, ip, c.Minor, want)
			if a.ifbOK {
				a.ensureFilter(ctx, "i", a.IFB, ip, c.Minor, want)
			}
		}
	}
	for key, handle := range a.filters {
		if want[key] {
			continue
		}
		dev, proto := a.Iface, "ip"
		if strings.HasPrefix(key, "i:") {
			dev = a.IFB
		}
		ip := key[2:]
		if strings.Contains(ip, ":") {
			proto = "ipv6"
		}
		a.run(ctx, "tc", "filter", "del", "dev", dev, "protocol", proto, "parent", "1:", "prio", "100", "handle", strconv.FormatUint(uint64(handle), 10))
		delete(a.filters, key)
	}
	for email, minor := range a.classOf {
		if _, ok := next[email]; ok {
			continue
		}
		a.dropClass(ctx, a.Iface, minor)
		if a.ifbOK {
			a.dropClass(ctx, a.IFB, minor)
		}
	}
	a.classOf = next
	return nil
}

func (a *Applier) setup(ctx context.Context) error {
	if err := a.runErr(ctx, "tc", "qdisc", "replace", "dev", a.Iface, "root", "handle", "1:", "htb", "default", "999"); err != nil {
		return err
	}
	a.run(ctx, "tc", "class", "replace", "dev", a.Iface, "parent", "1:", "classid", "1:999", "htb", "rate", "10000mbit", "ceil", "10000mbit")
	a.run(ctx, "tc", "qdisc", "replace", "dev", a.Iface, "parent", "1:999", "handle", "999:", "fq")
	if err := a.setupIFB(ctx); err != nil {
		log.Printf("shaper: upload redirect skipped: %v", err)
	}
	return nil
}

func (a *Applier) setupIFB(ctx context.Context) error {
	if !ifaceName.MatchString(a.IFB) {
		return fmt.Errorf("bad ifb name %q", a.IFB)
	}
	_ = a.runErr(ctx, "modprobe", "ifb", "numifbs=1")
	if err := a.runErr(ctx, "ip", "link", "add", a.IFB, "type", "ifb"); err != nil && !strings.Contains(err.Error(), "File exists") {
		return err
	}
	if err := a.runErr(ctx, "ip", "link", "set", a.IFB, "up"); err != nil {
		return err
	}
	if err := a.runErr(ctx, "tc", "qdisc", "replace", "dev", a.IFB, "root", "handle", "1:", "htb", "default", "999"); err != nil {
		return err
	}
	a.run(ctx, "tc", "class", "replace", "dev", a.IFB, "parent", "1:", "classid", "1:999", "htb", "rate", "10000mbit", "ceil", "10000mbit")
	a.run(ctx, "tc", "qdisc", "replace", "dev", a.IFB, "parent", "1:999", "handle", "999:", "fq")
	// Redirect ingress once. A second identical filter would duplicate every packet.
	// Replace the ingress qdisc so a restarted agent does not stack a second redirect.
	_ = a.runErr(ctx, "tc", "qdisc", "del", "dev", a.Iface, "ingress")
	if err := a.runErr(ctx, "tc", "qdisc", "add", "dev", a.Iface, "handle", "ffff:", "ingress"); err != nil {
		return err
	}
	if err := a.runErr(ctx, "tc", "filter", "add", "dev", a.Iface, "parent", "ffff:", "protocol", "ip", "prio", "1", "u32", "match", "u32", "0", "0", "action", "mirred", "egress", "redirect", "dev", a.IFB); err != nil {
		return err
	}
	a.ifbOK = true
	return nil
}

func (a *Applier) ensureClass(ctx context.Context, dev string, minor uint16) {
	id := fmt.Sprintf("1:%d", minor)
	parentQ := fmt.Sprintf("%d:", minor)
	a.run(ctx, "tc", "class", "replace", "dev", dev, "parent", "1:", "classid", id, "htb", "rate", a.rate, "ceil", a.rate)
	a.run(ctx, "tc", "qdisc", "replace", "dev", dev, "parent", id, "handle", parentQ, "fq")
}

func (a *Applier) ensureFilter(ctx context.Context, dir, dev, ip string, minor uint16, want map[string]bool) {
	key := dir + ":" + ip
	want[key] = true
	if _, ok := a.filters[key]; ok {
		return
	}
	handle := a.nextH
	a.nextH++
	proto, match := "ip", "dst"
	if dir == "i" {
		match = "src"
	}
	if strings.Contains(ip, ":") {
		proto = "ipv6"
		match = "ip6 " + match
	}
	args := []string{"filter", "add", "dev", dev, "protocol", proto, "parent", "1:", "prio", "100", "handle", strconv.FormatUint(uint64(handle), 10), "u32"}
	if proto == "ipv6" {
		field := "dst"
		if dir == "i" {
			field = "src"
		}
		args = append(args, "match", "ip6", field, ip, "flowid", fmt.Sprintf("1:%d", minor))
	} else {
		args = append(args, "match", "ip", match, ip+"/32", "flowid", fmt.Sprintf("1:%d", minor))
	}
	if err := a.runErr(ctx, "tc", args...); err != nil {
		log.Printf("shaper: filter %s %s: %v", dir, ip, err)
		return
	}
	a.filters[key] = handle
}

func (a *Applier) dropClass(ctx context.Context, dev string, minor uint16) {
	id := fmt.Sprintf("1:%d", minor)
	a.run(ctx, "tc", "qdisc", "del", "dev", dev, "parent", id)
	a.run(ctx, "tc", "class", "del", "dev", dev, "classid", id)
}

func (a *Applier) run(ctx context.Context, name string, args ...string) {
	if err := a.runErr(ctx, name, args...); err != nil {
		log.Printf("shaper: %v", err)
	}
}

func (a *Applier) runErr(ctx context.Context, name string, args ...string) error {
	return a.Exec(ctx, name, args...)
}
