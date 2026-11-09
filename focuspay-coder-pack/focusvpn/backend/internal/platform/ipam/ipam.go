// Package ipam allocates host IPs from an endpoint subnet (plans/M3 §6).
package ipam

import (
	"encoding/binary"
	"fmt"
	"net"
)

// NextHost picks the next free IPv4 host in cidr, skipping network, gateway (.1), and broadcast.
func NextHost(cidr string, used []string) (string, error) {
	_, ipnet, err := net.ParseCIDR(cidr)
	if err != nil {
		return "", fmt.Errorf("ipam: bad subnet %q: %w", cidr, err)
	}
	ones, bits := ipnet.Mask.Size()
	if bits != 32 {
		return "", fmt.Errorf("ipam: only IPv4 supported, got %s", cidr)
	}
	if ones > 30 {
		return "", fmt.Errorf("ipam: subnet too small: %s", cidr)
	}
	usedSet := make(map[string]struct{}, len(used))
	for _, u := range used {
		usedSet[u] = struct{}{}
	}
	base := ipnet.IP.To4()
	if base == nil {
		return "", fmt.Errorf("ipam: not IPv4: %s", cidr)
	}
	start := binary.BigEndian.Uint32(base)
	hostBits := uint32(32 - ones)
	count := uint32(1) << hostBits
	// i=0 network, i=1 gateway/DNS, i=last broadcast
	for i := uint32(2); i < count-1; i++ {
		ip := make(net.IP, 4)
		binary.BigEndian.PutUint32(ip, start+i)
		s := ip.String()
		if _, ok := usedSet[s]; !ok {
			return s, nil
		}
	}
	return "", fmt.Errorf("ipam: no free host in %s", cidr)
}
