package sublink

import (
	"fmt"
	"net/url"
	"strings"
)

// Server is one VLESS inbound as a Happ share-link sees it.
type Server struct {
	Node      string
	Country   string
	Address   string
	Port      int
	SNI       string
	Host      string
	Path      string
	Transport string
	Mode      string
}

// ShareLink builds one vless:// URI. remark is the name Happ shows.
func ShareLink(uuid string, srv Server, remark string) string {
	q := url.Values{}
	q.Set("encryption", "none")
	q.Set("security", "tls")
	q.Set("sni", srv.SNI)
	q.Set("fp", "chrome")
	q.Set("type", srv.Transport)
	q.Set("host", srv.Host)
	q.Set("path", srv.Path)
	if srv.Mode != "" {
		q.Set("mode", srv.Mode)
	}
	return fmt.Sprintf("vless://%s@%s:%d?%s#%s", uuid, srv.Address, srv.Port, q.Encode(), fragment(remark))
}

// ShareLinks names the first transport of a node plainly and the next ones
// with the transport, so two inbounds of DE2 are not the same row in Happ.
// XHTTP is left out: the VLESS fallback compares the path exactly, and an
// XHTTP client appends a session id, so the request hits the decoy site.
// The Focus app still receives XHTTP and walks to WebSocket on its own.
func ShareLinks(uuid string, servers []Server) []string {
	seen := map[string]int{}
	var out []string
	for _, srv := range servers {
		if !strings.EqualFold(srv.Transport, "ws") {
			continue
		}
		if uuid == "" || srv.Address == "" || srv.Port == 0 || srv.Path == "" || srv.Transport == "" {
			continue
		}
		name := place(srv.Country, srv.Node)
		if seen[srv.Node] > 0 {
			name += " · " + transportLabel(srv.Transport)
		}
		seen[srv.Node]++
		out = append(out, ShareLink(uuid, srv, name))
	}
	return out
}

func fragment(remark string) string {
	return strings.ReplaceAll(url.QueryEscape(remark), "+", "%20")
}

func transportLabel(transport string) string {
	switch strings.ToLower(transport) {
	case "xhttp":
		return "XHTTP"
	case "ws":
		return "WS"
	default:
		return strings.ToUpper(transport)
	}
}

func place(country, node string) string {
	name := countryNames[strings.ToUpper(strings.TrimSpace(country))]
	if name == "" {
		name = strings.ToUpper(strings.TrimSpace(country))
	}
	node = strings.TrimSpace(node)
	if name == "" {
		return node
	}
	if node == "" {
		return name
	}
	return name + " · " + node
}

var countryNames = map[string]string{
	"NL": "Нидерланды",
	"DE": "Германия",
	"RO": "Румыния",
	"FI": "Финляндия",
	"CH": "Швейцария",
	"GB": "Великобритания",
	"UK": "Великобритания",
	"US": "США",
	"JP": "Япония",
	"SG": "Сингапур",
	"FR": "Франция",
	"SE": "Швеция",
	"PL": "Польша",
	"CA": "Канада",
}
