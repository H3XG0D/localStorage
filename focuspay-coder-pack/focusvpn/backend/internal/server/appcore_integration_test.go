package server_test

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	appclient "focusvpn.example/focusvpn/clients/appcore/client"
	"focusvpn.example/focusvpn/clients/appcore/engine"
	appstorage "focusvpn.example/focusvpn/clients/appcore/storage"
)

// TestAppCoreAgainstCP exercises Phase 3 AppCore against the real CP handler.
func TestAppCoreAgainstCP(t *testing.T) {
	ts, st := newTestServerWithStore(t)
	defer ts.Close()

	storeMem := appstorage.NewMemory()
	app, err := appclient.New(appclient.Options{
		APIBase: ts.URL, Store: storeMem, Engine: engine.NewDryRun(), ConfDir: t.TempDir(), DryRun: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err := app.Register(ctx, "appcore-p3@example.com", "supersecret-appcore-1"); err != nil {
		t.Fatalf("register: %v", err)
	}
	grantAccess(t, st, "appcore-p3@example.com")
	res, err := app.Connect(ctx)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	raw, err := os.ReadFile(res.Assembled.ConfPath)
	if err != nil {
		t.Fatal(err)
	}
	s := string(raw)
	for _, want := range []string{"Jc = ", "Jmin = ", "Jmax = ", "S1 = ", "H1 = ", "[Peer]"} {
		if !strings.Contains(s, want) {
			t.Fatalf("conf missing %q\n%s", want, s)
		}
	}
	if err := app.Disconnect(ctx); err != nil {
		t.Fatalf("disconnect: %v", err)
	}
	if !app.Status().LoggedIn {
		t.Fatal("expected logged in")
	}
}

// TestAppCoreFailoverWalk fails the first engine Start, then succeeds on the next candidate.
func TestAppCoreFailoverWalk(t *testing.T) {
	ts, st := newTestServerWithStore(t)
	defer ts.Close()

	eng := engine.NewFailN(1)
	app, err := appclient.New(appclient.Options{
		APIBase: ts.URL, Store: appstorage.NewMemory(), Engine: eng, ConfDir: t.TempDir(), DryRun: true,
		Sleep:        func(time.Duration) {},
		FailoverBase: time.Millisecond,
		FailoverCap:  5 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err := app.Register(ctx, "failover@example.com", "supersecret-failover-1"); err != nil {
		t.Fatalf("register: %v", err)
	}
	grantAccess(t, st, "failover@example.com")
	res, err := app.Connect(ctx)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	if eng.Starts() < 2 {
		t.Fatalf("expected >=2 Start attempts, got %d", eng.Starts())
	}
	if len(res.Candidates) < 2 {
		t.Fatalf("expected multi-candidate list: %+v", res.Candidates)
	}
	if err := app.Disconnect(ctx); err != nil {
		t.Fatalf("disconnect: %v", err)
	}
}
