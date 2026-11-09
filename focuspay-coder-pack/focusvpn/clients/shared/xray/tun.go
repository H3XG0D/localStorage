package xray

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
)

// TunInterface is the device xray creates (Linux tun, Windows wintun.dll).
const TunInterface = "xray0"

// SocksPort is the local probe inbound. Same port as the Android client.
const SocksPort = 10808

// VlessServer is one entry from ConfigParts["xray"].servers.
type VlessServer struct {
	Node      string
	Address   string
	Port      int
	SNI       string
	Host      string
	Path      string
	Transport string
	Mode      string
}

// VlessProfile is what the desktop tunnel needs. The UUID comes from the control plane.
type VlessProfile struct {
	UUID    string
	Servers []VlessServer
}

// ProfileFromParts reads the VLESS credential Android uses (uuid + server list).
func ProfileFromParts(parts map[string]any) (VlessProfile, error) {
	raw, _ := parts["xray"].(map[string]any)
	if raw == nil {
		return VlessProfile{}, errors.New("xray: parts.xray missing")
	}
	uuid, _ := raw["uuid"].(string)
	if uuid == "" {
		return VlessProfile{}, errors.New("xray: uuid required")
	}
	var servers []VlessServer
	if list, ok := raw["servers"].([]any); ok {
		for _, item := range list {
			m, ok := item.(map[string]any)
			if !ok {
				continue
			}
			servers = append(servers, serverFrom(m))
		}
	}
	if len(servers) == 0 {
		servers = []VlessServer{serverFrom(raw)}
	}
	if len(servers) == 0 {
		return VlessProfile{}, errors.New("xray: server address and path are required")
	}
	for _, s := range servers {
		if s.Address == "" || s.Path == "" {
			return VlessProfile{}, errors.New("xray: server address and path are required")
		}
	}
	return VlessProfile{UUID: uuid, Servers: servers}, nil
}

func serverFrom(o map[string]any) VlessServer {
	transport, _ := o["transport"].(string)
	if transport == "" {
		transport, _ = o["network"].(string)
	}
	if transport == "" {
		transport = "ws"
	}
	host, _ := o["host"].(string)
	if host == "" {
		host, _ = o["sni"].(string)
	}
	address, _ := o["address"].(string)
	if address == "" {
		address = host
	}
	if host == "" {
		host = address
	}
	sni, _ := o["sni"].(string)
	if sni == "" {
		sni = host
	}
	path, _ := o["path"].(string)
	mode, _ := o["mode"].(string)
	node, _ := o["node"].(string)
	if node == "" {
		node = address
	}
	port := 443
	if p, ok := asInt(o["port"]); ok && p > 0 {
		port = p
	}
	return VlessServer{
		Node: node, Address: address, Port: port, SNI: sni, Host: host,
		Path: path, Transport: transport, Mode: mode,
	}
}

// BuildTunDocument is the Xray JSON a desktop process runs. Unlike Android,
// there is no VpnService fd: xray creates TunInterface itself.
// prefixes are RIPE-RU CIDRs (private ranges are always included).
func BuildTunDocument(server VlessServer, uuid string, prefixes []string) (map[string]any, error) {
	if uuid == "" || server.Address == "" || server.Path == "" || server.Port <= 0 {
		return nil, errors.New("xray: incomplete tun config")
	}
	domains := domainRules()
	return map[string]any{
		"log": map[string]any{"loglevel": "warning"},
		"dns": map[string]any{
			"queryStrategy": "UseIPv4",
			"servers": []any{
				map[string]any{
					"address": "77.88.8.8",
					"port":    53,
					"domains": domains,
				},
				"https://1.1.1.1/dns-query",
			},
		},
		"inbounds": []any{
			map[string]any{
				"tag":      "tun-in",
				"port":     0,
				"protocol": "tun",
				"settings": map[string]any{
					"name": TunInterface,
					"MTU":  1400,
					// Without these, Xray only creates the interface. The system
					// default route stays on the physical NIC, so browsers keep
					// the machine's own address.
					"gateway":                []any{"10.255.0.1/30"},
					"autoSystemRoutingTable": []any{"0.0.0.0/0"},
					"autoOutboundsInterface": "auto",
				},
				"sniffing": map[string]any{
					"enabled": true,
					"destOverride": []any{
						"http", "tls", "quic",
					},
				},
			},
			map[string]any{
				"tag":      "socks-in",
				"listen":   "127.0.0.1",
				"port":     SocksPort,
				"protocol": "socks",
				"settings": map[string]any{"udp": false},
			},
		},
		"outbounds": []any{
			map[string]any{
				"tag":      "proxy",
				"protocol": "vless",
				"settings": map[string]any{
					"vnext": []any{
						map[string]any{
							"address": server.Address,
							"port":    server.Port,
							"users": []any{
								map[string]any{
									"id":         uuid,
									"encryption": "none",
								},
							},
						},
					},
				},
				"streamSettings": tunStream(server),
			},
			map[string]any{
				"tag":      "dns-out",
				"protocol": "dns",
			},
			map[string]any{
				"tag":      "direct",
				"protocol": "freedom",
				"settings": map[string]any{"domainStrategy": "UseIPv4"},
			},
		},
		"routing": map[string]any{
			"domainStrategy": "IPIfNonMatch",
			"rules": []any{
				map[string]any{
					"type":        "field",
					"inboundTag":  []any{"tun-in"},
					"port":        53,
					"outboundTag": "dns-out",
				},
				map[string]any{
					"type":        "field",
					"domain":      domains,
					"outboundTag": "direct",
				},
				map[string]any{
					"type":        "field",
					"ip":          ipRules(prefixes),
					"outboundTag": "direct",
				},
			},
		},
	}, nil
}

func tunStream(server VlessServer) map[string]any {
	stream := map[string]any{
		"network":  server.Transport,
		"security": "tls",
		"tlsSettings": map[string]any{
			"serverName":  server.SNI,
			"fingerprint": "chrome",
			"alpn":        []any{"http/1.1"},
		},
	}
	if server.Transport == "xhttp" {
		xs := map[string]any{"path": server.Path}
		if server.Host != "" {
			xs["host"] = server.Host
		}
		if server.Mode != "" {
			xs["mode"] = server.Mode
		}
		stream["xhttpSettings"] = xs
		return stream
	}
	stream["wsSettings"] = map[string]any{
		"path":    server.Path,
		"headers": map[string]any{"Host": server.Host},
	}
	return stream
}

// WriteTunJSON writes a tun client document (0600) and checks it is still VLESS+TLS.
func WriteTunJSON(dir, name string, server VlessServer, uuid string, prefixes []string) (string, error) {
	if name == "" {
		name = "xray-client.json"
	}
	doc, err := BuildTunDocument(server, uuid, prefixes)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return "", err
	}
	var check Document
	if err := json.Unmarshal(raw, &check); err != nil {
		return "", err
	}
	if err := ValidateDocument(check); err != nil {
		return "", err
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		return "", err
	}
	return path, nil
}
