package shaper

import (
	"context"
	"strings"
	"testing"
)

func TestSyncPlansOneHundredMegabitClassForBothAddresses(t *testing.T) {
	var cmds []string
	a := NewApplier(func(_ context.Context, name string, args ...string) error {
		cmds = append(cmds, name+" "+strings.Join(args, " "))
		return nil
	}, "eth0", "ifb-fvpn", 100)
	err := a.Sync(context.Background(), map[string][]string{
		"user-a": {"203.0.113.10", "203.0.113.11"},
	})
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(cmds, "\n")
	if strings.Count(joined, "rate 100mbit ceil 100mbit") != 2 {
		t.Fatalf("want one 100mbit class on egress and one on ifb:\n%s", joined)
	}
	if !strings.Contains(joined, "match ip dst 203.0.113.10/32") || !strings.Contains(joined, "match ip dst 203.0.113.11/32") {
		t.Fatalf("both addresses must share the download class:\n%s", joined)
	}
	if !strings.Contains(joined, "match ip src 203.0.113.10/32") || !strings.Contains(joined, "dev ifb-fvpn") {
		t.Fatalf("upload must be shaped on ifb:\n%s", joined)
	}
	if strings.Contains(joined, "10.66.0.1") {
		t.Fatal("local bind address must not be classified")
	}
}
