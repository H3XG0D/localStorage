package nodeagent_test

import (
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"net/http"
)

// withFakeTLSCN injects a fake *tls.ConnectionState so that nodeIDFromTLS
// returns the given CN (simulates mTLS without a real TLS handshake).
func withFakeTLSCN(r *http.Request, cn string) *http.Request {
	cert := &x509.Certificate{Subject: pkix.Name{CommonName: cn}}
	r.TLS = &tls.ConnectionState{
		PeerCertificates: []*x509.Certificate{cert},
	}
	return r
}
