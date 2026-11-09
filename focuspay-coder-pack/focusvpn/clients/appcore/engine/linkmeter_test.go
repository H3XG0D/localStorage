package engine

import (
	"testing"
	"time"
)

func TestThroughputMbps(t *testing.T) {
	down, up, ok := throughputMbps(0, 0, 1_000_000, 500_000, time.Second)
	if !ok || down < 7.9 || down > 8.1 || up < 3.9 || up > 4.1 {
		t.Fatalf("down %v up %v ok %v", down, up, ok)
	}
	if _, _, ok := throughputMbps(0, 0, 10, 10, 100*time.Millisecond); ok {
		t.Fatal("short interval")
	}
	if _, _, ok := throughputMbps(100, 0, 50, 10, time.Second); ok {
		t.Fatal("backwards counter")
	}
}
