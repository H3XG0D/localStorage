package telemetry

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"focusvpn.example/focusvpn/node-agent/internal/mtls"
)

func TestTrafficDeltaSurvivesFailedPost(t *testing.T) {
	var got []telemetryPayload
	fail := true
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var p telemetryPayload
		_ = json.NewDecoder(r.Body).Decode(&p)
		got = append(got, p)
		if fail {
			w.WriteHeader(http.StatusBadGateway)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()

	s := New(mtls.NewWithHTTP(srv.URL, srv.Client()), "node-1", time.Minute)
	counters := Sample{Online: 1, Downlink: 100, Uplink: 10}
	s.SetCollector(func(context.Context) (Sample, error) { return counters, nil })
	s.MarkApplied([]string{"alloc-1"})
	ctx := context.Background()

	if err := s.send(ctx); err == nil {
		t.Fatal("want error on 502")
	}
	fail = false
	counters = Sample{Online: 1, Downlink: 150, Uplink: 15}
	if err := s.send(ctx); err != nil {
		t.Fatal(err)
	}
	counters = Sample{Online: 1, Downlink: 170, Uplink: 20}
	if err := s.send(ctx); err != nil {
		t.Fatal(err)
	}
	counters = Sample{Online: 0, Downlink: 5, Uplink: 1} // Xray restarted
	if err := s.send(ctx); err != nil {
		t.Fatal(err)
	}

	if got[0].Seq != got[1].Seq || got[0].Boot != got[1].Boot {
		t.Fatalf("retry must reuse seq: %d vs %d", got[0].Seq, got[1].Seq)
	}
	if got[0].RxBytes != 100 || got[1].RxBytes != 150 {
		t.Fatalf("retry must resend the grown delta: %d, %d", got[0].RxBytes, got[1].RxBytes)
	}
	if len(got[1].Peers) != 1 || got[1].Peers[0].AllocationID != "alloc-1" {
		t.Fatalf("applied peers must be requeued after a failed POST: %+v", got[1].Peers)
	}
	if got[2].Seq != got[1].Seq+1 || got[2].RxBytes != 20 || got[2].TxBytes != 5 {
		t.Fatalf("after success delta starts from accepted counters: %+v", got[2])
	}
	if got[3].RxBytes != 5 || got[3].TxBytes != 1 {
		t.Fatalf("counter reset must not produce a negative delta: %+v", got[3])
	}
}
