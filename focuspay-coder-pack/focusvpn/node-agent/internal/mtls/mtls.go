// Package mtls provides mTLS HTTP client construction and initial registration
// for the node agent (ADR-004).
package mtls

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// Client wraps an http.Client that uses an mTLS certificate for the CP agent
// listener. It is safe for concurrent use.
type Client struct {
	inner *http.Client
	cpURL string
}

// Register performs a one-time registration against the CP: it generates an
// ECDSA P-256 key + CSR, sends it with the node_token, and writes the returned
// cert + CA to disk. After registration the agent should reload itself with a
// full mTLS client.
func Register(cpURL, nodeToken, certFile, keyFile, caFile string) error {
	// Generate ephemeral key for CSR.
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return fmt.Errorf("mtls: keygen: %w", err)
	}
	csrPEM, err := generateCSR(priv)
	if err != nil {
		return fmt.Errorf("mtls: generate CSR: %w", err)
	}

	body, _ := json.Marshal(map[string]string{
		"node_token": nodeToken,
		"csr_pem":    string(csrPEM),
	})

	// Use a plain TLS client that still verifies server cert via CA file if present,
	// otherwise skip verify (dev only — CA not yet distributed).
	tlsCfg := &tls.Config{InsecureSkipVerify: false} //nolint:gosec
	if raw, err := os.ReadFile(caFile); err == nil {
		pool := x509.NewCertPool()
		pool.AppendCertsFromPEM(raw)
		tlsCfg.RootCAs = pool
	} else {
		// CA file not yet present during first-time registration.
		tlsCfg.InsecureSkipVerify = true //nolint:gosec
		fmt.Printf("WARN: CA file %s not found; skipping server cert verification for registration (expected on first boot)\n", caFile)
	}
	plain := &http.Client{
		Timeout:   30 * time.Second,
		Transport: &http.Transport{TLSClientConfig: tlsCfg},
	}

	resp, err := plain.Post(cpURL+"/v1/agent/register", "application/json", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("mtls: register POST: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("mtls: register failed (%d): %s", resp.StatusCode, data)
	}

	var result struct {
		CertPEM string `json:"cert_pem"`
		CAPEM   string `json:"ca_pem"`
	}
	if err := json.Unmarshal(data, &result); err != nil {
		return fmt.Errorf("mtls: parse register response: %w", err)
	}

	// Write cert.
	if err := os.WriteFile(certFile, []byte(result.CertPEM), 0600); err != nil {
		return fmt.Errorf("mtls: write cert: %w", err)
	}
	// Write key.
	keyDER, err := x509.MarshalECPrivateKey(priv)
	if err != nil {
		return fmt.Errorf("mtls: marshal key: %w", err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	if err := os.WriteFile(keyFile, keyPEM, 0600); err != nil {
		return fmt.Errorf("mtls: write key: %w", err)
	}
	// Write CA.
	if err := os.WriteFile(caFile, []byte(result.CAPEM), 0644); err != nil {
		return fmt.Errorf("mtls: write CA: %w", err)
	}
	fmt.Printf("mtls: registration complete; cert written to %s\n", certFile)
	return nil
}

// NewClient loads the mTLS cert+key and builds an HTTP client that presents
// the client certificate and verifies the server against caFile.
func NewClient(cpURL, certFile, keyFile, caFile string) (*Client, error) {
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("mtls: load cert/key: %w", err)
	}
	caPEM, err := os.ReadFile(caFile)
	if err != nil {
		return nil, fmt.Errorf("mtls: read CA: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, errors.New("mtls: no CA certs found in ca file")
	}
	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
		MinVersion:   tls.VersionTLS13,
	}
	return &Client{
		inner: &http.Client{
			Timeout:   35 * time.Second, // > long-poll timeout on server
			Transport: &http.Transport{TLSClientConfig: tlsCfg},
		},
		cpURL: cpURL,
	}, nil
}

// Do executes an HTTP request using the mTLS client.
func (c *Client) Do(req *http.Request) (*http.Response, error) {
	return c.inner.Do(req)
}

// NewWithHTTP wraps an already configured HTTP client (tests, custom transports).
func NewWithHTTP(cpURL string, hc *http.Client) *Client {
	return &Client{inner: hc, cpURL: cpURL}
}

// CPURL returns the base CP URL.
func (c *Client) CPURL() string { return c.cpURL }

// generateCSR creates a PKCS#10 CSR signed by priv with an empty subject CN
// (filled in by the CP from the node token).
func generateCSR(priv *ecdsa.PrivateKey) ([]byte, error) {
	tmpl := &x509.CertificateRequest{
		Subject:            pkix.Name{CommonName: "node-agent"},
		SignatureAlgorithm: x509.ECDSAWithSHA256,
	}
	raw, err := x509.CreateCertificateRequest(rand.Reader, tmpl, priv)
	if err != nil {
		return nil, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: raw}), nil
}
