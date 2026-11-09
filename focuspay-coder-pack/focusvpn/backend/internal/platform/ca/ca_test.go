package ca_test

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/ca"
)

func TestEphemeralCA(t *testing.T) {
	authority, err := ca.LoadOrEphemeral("", "")
	if err != nil {
		t.Fatalf("load: %v", err)
	}

	caPEM := authority.CertPEM()
	if len(caPEM) == 0 {
		t.Fatal("empty CA PEM")
	}
	block, _ := pem.Decode(caPEM)
	if block == nil {
		t.Fatal("invalid PEM")
	}
}

func TestSignCSR(t *testing.T) {
	authority, err := ca.LoadOrEphemeral("", "")
	if err != nil {
		t.Fatalf("load: %v", err)
	}

	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	tmpl := &x509.CertificateRequest{
		Subject: pkix.Name{CommonName: "test-node"},
	}
	raw, err := x509.CreateCertificateRequest(rand.Reader, tmpl, priv)
	if err != nil {
		t.Fatalf("csr: %v", err)
	}
	csrPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: raw})

	certPEM, serial, err := authority.SignCSR(csrPEM, "test-node", 24*time.Hour)
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	if serial <= 0 {
		t.Fatalf("serial should be > 0, got %d", serial)
	}
	block, _ := pem.Decode(certPEM)
	if block == nil {
		t.Fatal("cert PEM invalid")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatalf("parse cert: %v", err)
	}
	if cert.Subject.CommonName != "test-node" {
		t.Fatalf("expected CN=test-node, got %s", cert.Subject.CommonName)
	}
}

func TestGenerateServerCert(t *testing.T) {
	authority, err := ca.LoadOrEphemeral("", "")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	tlsCert, err := authority.GenerateServerCert("cp.focusvpn.internal", 24*time.Hour)
	if err != nil {
		t.Fatalf("server cert: %v", err)
	}
	if len(tlsCert.Certificate) == 0 {
		t.Fatal("empty certificate chain")
	}
}
