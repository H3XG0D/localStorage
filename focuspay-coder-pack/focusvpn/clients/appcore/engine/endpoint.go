package engine

import (
	"fmt"
	"net"
)

// resolveEndpointForUAPI turns host:port into ip:port (userspace ParseEndpoint is IP-only).
// In dry-run, unresolvable demo hostnames fall back to 127.0.0.1 so CI can exercise IpcSet.
func resolveEndpointForUAPI(endpoint string, dryRun bool) (string, error) {
	host, port, err := net.SplitHostPort(endpoint)
	if err != nil {
		return "", fmt.Errorf("engine: endpoint: %w", err)
	}
	if ip := net.ParseIP(host); ip != nil {
		return endpoint, nil
	}
	ips, err := net.LookupIP(host)
	if err != nil || len(ips) == 0 {
		if dryRun {
			return net.JoinHostPort("127.0.0.1", port), nil
		}
		if err != nil {
			return "", fmt.Errorf("engine: resolve %s: %w", host, err)
		}
		return "", fmt.Errorf("engine: resolve %s: no A/AAAA", host)
	}
	chosen := ips[0]
	for _, ip := range ips {
		if ip.To4() != nil {
			chosen = ip
			break
		}
	}
	return net.JoinHostPort(chosen.String(), port), nil
}
