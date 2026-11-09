// Package shaper caps each VLESS user at 100 Mbit/s. Xray has no per-user
// rate, so the limit is a Linux tc class shared by every public address of
// that user. Addresses stay on the node; the control plane only hears counts.
package shaper

import (
	"net"
	"sort"
)

const (
	// Rate is the per-user ceiling. tc's "mbit" is megabits per second.
	Rate = "100mbit"
	// MaxPublicIPs is how many public addresses one UUID may hold at once.
	// A phone on IPv4 and IPv6 plus one network change fits; a fourth does not.
	MaxPublicIPs = 3
	// defaultMinor is the first HTB class minor. 999 is the uncapped default.
	defaultMinor = 10
	maxMinor     = 998
)

// Share is a UUID seen from more public addresses than MaxPublicIPs.
type Share struct {
	Email string
	Count int
}

// Class is one user's tc class and the addresses that belong to it.
type Class struct {
	Email string
	Minor uint16
	IPs   []string
}

// Public drops loopback, private, link-local and unparseable addresses.
// 10.66.0.1 (the old Nginx bind) is private and falls out here.
func Public(ips []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, raw := range ips {
		ip := net.ParseIP(raw)
		if ip == nil || !isPublic(ip) {
			continue
		}
		s := ip.String()
		if seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

func isPublic(ip net.IP) bool {
	if ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsUnspecified() || ip.IsMulticast() {
		return false
	}
	return true
}

// Classify keeps a public-address set per user and lists users over the cap.
// Over-limit users are still shaped: the pause is decided by the caller.
func Classify(users map[string][]string, max int) (shaped map[string][]string, over []Share) {
	if max <= 0 {
		max = MaxPublicIPs
	}
	shaped = map[string][]string{}
	var emails []string
	for email := range users {
		emails = append(emails, email)
	}
	sort.Strings(emails)
	for _, email := range emails {
		pub := Public(users[email])
		if len(pub) == 0 {
			continue
		}
		shaped[email] = pub
		if len(pub) > max {
			over = append(over, Share{Email: email, Count: len(pub)})
		}
	}
	return shaped, over
}

// Assign gives each email a stable class minor. prev is the last assignment
// and is reused so filters do not move between classes every tick.
func Assign(shaped map[string][]string, prev map[string]uint16) (classes []Class, next map[string]uint16) {
	next = map[string]uint16{}
	used := map[uint16]bool{}
	var emails []string
	for email := range shaped {
		emails = append(emails, email)
	}
	sort.Strings(emails)
	for _, email := range emails {
		if id, ok := prev[email]; ok && id >= defaultMinor && id <= maxMinor && !used[id] {
			next[email] = id
			used[id] = true
		}
	}
	minor := uint16(defaultMinor)
	for _, email := range emails {
		if _, ok := next[email]; ok {
			continue
		}
		for minor <= maxMinor && used[minor] {
			minor++
		}
		if minor > maxMinor {
			break
		}
		next[email] = minor
		used[minor] = true
		minor++
	}
	for _, email := range emails {
		id, ok := next[email]
		if !ok {
			continue
		}
		classes = append(classes, Class{Email: email, Minor: id, IPs: append([]string(nil), shaped[email]...)})
	}
	return classes, next
}
