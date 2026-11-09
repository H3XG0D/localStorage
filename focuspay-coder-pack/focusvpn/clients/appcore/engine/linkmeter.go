package engine

import (
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type ifaceSample struct {
	at time.Time
	rx uint64
	tx uint64
}

var linkMeter struct {
	mu   sync.Mutex
	prev map[string]ifaceSample
}

// SampleMbps is the rate since the previous read of iface, in megabits per second.
// ok is false until two reads are at least 200ms apart, or when the counters
// went backwards (the tunnel was recreated).
func SampleMbps(iface string) (down, up float64, ok bool) {
	rx, tx, readOK := readIfaceCounters(iface)
	if !readOK {
		return 0, 0, false
	}
	now := time.Now()
	linkMeter.mu.Lock()
	defer linkMeter.mu.Unlock()
	if linkMeter.prev == nil {
		linkMeter.prev = map[string]ifaceSample{}
	}
	prev, has := linkMeter.prev[iface]
	linkMeter.prev[iface] = ifaceSample{at: now, rx: rx, tx: tx}
	if !has {
		return 0, 0, false
	}
	return throughputMbps(prev.rx, prev.tx, rx, tx, now.Sub(prev.at))
}

func throughputMbps(beforeRx, beforeTx, afterRx, afterTx uint64, elapsed time.Duration) (down, up float64, ok bool) {
	if elapsed < 200*time.Millisecond {
		return 0, 0, false
	}
	if afterRx < beforeRx || afterTx < beforeTx {
		return 0, 0, false
	}
	seconds := elapsed.Seconds()
	down = float64(afterRx-beforeRx) * 8 / seconds / 1_000_000
	up = float64(afterTx-beforeTx) * 8 / seconds / 1_000_000
	return down, up, true
}

func readIfaceCounters(iface string) (rx, tx uint64, ok bool) {
	if iface == "" || strings.Contains(iface, "/") || strings.Contains(iface, "..") {
		return 0, 0, false
	}
	rx, ok1 := readUintFile("/sys/class/net/" + iface + "/statistics/rx_bytes")
	tx, ok2 := readUintFile("/sys/class/net/" + iface + "/statistics/tx_bytes")
	return rx, tx, ok1 && ok2
}

func readUintFile(path string) (uint64, bool) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	n, err := strconv.ParseUint(strings.TrimSpace(string(b)), 10, 64)
	if err != nil {
		return 0, false
	}
	return n, true
}
