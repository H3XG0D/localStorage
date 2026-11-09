// Package ca implements the internal Certificate Authority used for node-agent
// mTLS (ADR-004). In Phase 2 the CA key lives on disk under secrets/; prod
// should use a managed PKI. All crypto is stdlib only — no new dependencies.
package ca

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"net"
	"os"
	"sync/atomic"
	"time"
)

// CA is a loaded certificate authority able to sign node CSRs.
type CA struct {
	cert   *x509.Certificate
	key    *ecdsa.PrivateKey
	serial atomic.Int64 // monotonic serial counter (in-process only)
}

// Load reads a PEM-encoded CA certificate and ECDSA private key from disk.
// If the files do not exist it generates an ephemeral dev CA and logs a warning.
func Load(certPath, keyPath string) (*CA, error) {
	certPEM, certErr := os.ReadFile(certPath)
	keyPEM, keyErr := os.ReadFile(keyPath)
	if certErr == nil && keyErr == nil {
		return parsePEM(certPEM, keyPEM)
	}
	if !errors.Is(certErr, os.ErrNotExist) && certErr != nil {
		return nil, fmt.Errorf("ca: read cert: %w", certErr)
	}
	// Ephemeral dev CA — acceptable only in local development.
	fmt.Printf("WARN: CA files not found (%s / %s); generating ephemeral dev CA (NOT for production)\n", certPath, keyPath)
	return generateEphemeral()
}

// LoadOrEphemeral is a convenience wrapper; always returns a usable CA.
func LoadOrEphemeral(certPath, keyPath string) (*CA, error) {
	return Load(certPath, keyPath)
}

// CertPEM returns the CA certificate in PEM form (for distribution to agents).
func (c *CA) CertPEM() []byte {
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: c.cert.Raw})
}

// TLSConfig returns a *tls.Config that requires client certificates signed by
// this CA. Use for the agent-facing HTTPS listener.
func (c *CA) TLSConfig(serverCert tls.Certificate) *tls.Config {
	pool := x509.NewCertPool()
	pool.AddCert(c.cert)
	return &tls.Config{
		Certificates: []tls.Certificate{serverCert},
		// Registration has no client cert yet (one-time token). State and
		// telemetry handlers reject requests that did not present one.
		// A presented cert is still verified against this CA.
		ClientAuth: tls.VerifyClientCertIfGiven,
		ClientCAs:  pool,
		MinVersion: tls.VersionTLS13,
	}
}

// SignCSR signs a PEM-encoded CSR and returns a PEM-encoded certificate valid
// for ttl. The returned certificate has the node CN from the CSR.
// SignCSR signs a PEM-encoded CSR. commonName is the node id and overrides
// whatever the CSR asked for, so a client cannot claim another node's identity.
func (c *CA) SignCSR(csrPEM []byte, commonName string, ttl time.Duration) (certPEM []byte, serial int64, err error) {
	if commonName == "" {
		return nil, 0, errors.New("ca: common name required")
	}
	block, _ := pem.Decode(csrPEM)
	if block == nil || block.Type != "CERTIFICATE REQUEST" {
		return nil, 0, errors.New("ca: invalid CSR PEM")
	}
	csr, err := x509.ParseCertificateRequest(block.Bytes)
	if err != nil {
		return nil, 0, fmt.Errorf("ca: parse CSR: %w", err)
	}
	if err := csr.CheckSignature(); err != nil {
		return nil, 0, fmt.Errorf("ca: CSR signature invalid: %w", err)
	}

	serial = c.nextSerial()
	now := time.Now().UTC()
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(serial),
		Subject:      pkix.Name{CommonName: commonName, Organization: []string{"FocusVPN"}},
		NotBefore:    now.Add(-30 * time.Second),
		NotAfter:     now.Add(ttl),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	raw, err := x509.CreateCertificate(rand.Reader, tmpl, c.cert, csr.PublicKey, c.key)
	if err != nil {
		return nil, 0, fmt.Errorf("ca: sign: %w", err)
	}
	certPEM = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: raw})
	return certPEM, serial, nil
}

// GenerateServerCert creates an ECDSA P-256 TLS certificate for the CP agent
// listener, signed by this CA.
func (c *CA) GenerateServerCert(cn string, ttl time.Duration) (tls.Certificate, error) {
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, err
	}
	serial := c.nextSerial()
	now := time.Now().UTC()
	dns := []string{"localhost"}
	var ips []net.IP
	if ip := net.ParseIP(cn); ip != nil {
		ips = append(ips, ip)
	} else if cn != "" {
		dns = append(dns, cn)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(serial),
		Subject:      pkix.Name{CommonName: cn, Organization: []string{"FocusVPN"}},
		DNSNames:     dns,
		IPAddresses:  ips,
		NotBefore:    now.Add(-30 * time.Second),
		NotAfter:     now.Add(ttl),
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	raw, err := x509.CreateCertificate(rand.Reader, tmpl, c.cert, &priv.PublicKey, c.key)
	if err != nil {
		return tls.Certificate{}, err
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: raw})
	keyDER, err := x509.MarshalECPrivateKey(priv)
	if err != nil {
		return tls.Certificate{}, err
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	return tls.X509KeyPair(certPEM, keyPEM)
}

func (c *CA) nextSerial() int64 {
	// Random, not a process-local counter: the counter restarted at the CA
	// serial on every process start and collided with node_certificates.serial.
	n, err := rand.Int(rand.Reader, big.NewInt(1<<62))
	if err != nil {
		panic("ca: serial: " + err.Error())
	}
	v := n.Int64()
	if v <= 0 {
		v = 1
	}
	return v
}

func parsePEM(certPEM, keyPEM []byte) (*CA, error) {
	block, _ := pem.Decode(certPEM)
	if block == nil {
		return nil, errors.New("ca: invalid cert PEM")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("ca: parse cert: %w", err)
	}
	kb, _ := pem.Decode(keyPEM)
	if kb == nil {
		return nil, errors.New("ca: invalid key PEM")
	}
	key, err := x509.ParseECPrivateKey(kb.Bytes)
	if err != nil {
		return nil, fmt.Errorf("ca: parse key: %w", err)
	}
	ca := &CA{cert: cert, key: key}
	// Seed serial above the cert's own serial to avoid collisions.
	ca.serial.Store(cert.SerialNumber.Int64())
	return ca, nil
}

func generateEphemeral() (*CA, error) {
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "FocusVPN Dev CA", Organization: []string{"FocusVPN"}},
		NotBefore:             now.Add(-30 * time.Second),
		NotAfter:              now.Add(365 * 24 * time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
	}
	raw, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &priv.PublicKey, priv)
	if err != nil {
		return nil, err
	}
	cert, err := x509.ParseCertificate(raw)
	if err != nil {
		return nil, err
	}
	ca := &CA{cert: cert, key: priv}
	ca.serial.Store(1)
	return ca, nil
}
