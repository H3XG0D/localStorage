package shaper

import "testing"

func TestPublicDropsLocalAndBindAddress(t *testing.T) {
	got := Public([]string{"10.66.0.1", "127.0.0.1", "192.168.1.9", "::1", "203.0.113.10", "203.0.113.10", "not-an-ip"})
	if len(got) != 1 || got[0] != "203.0.113.10" {
		t.Fatalf("public: %v", got)
	}
}

func TestClassifySharesOneClassAcrossAddresses(t *testing.T) {
	shaped, over := Classify(map[string][]string{
		"user-a": {"203.0.113.10", "203.0.113.11", "10.66.0.1"},
		"user-b": {"198.51.100.2", "198.51.100.3", "198.51.100.4", "198.51.100.5"},
		"local":  {"10.1.1.1"},
	}, MaxPublicIPs)
	if len(shaped["user-a"]) != 2 || len(over) != 0 && over[0].Email == "user-a" {
		t.Fatalf("user-a should stay under the cap: shaped=%v over=%v", shaped["user-a"], over)
	}
	if _, ok := shaped["local"]; ok {
		t.Fatal("private-only user must not be shaped")
	}
	if len(over) != 1 || over[0].Email != "user-b" || over[0].Count != 4 {
		t.Fatalf("over: %+v", over)
	}
	classes, ids := Assign(shaped, nil)
	byEmail := map[string]Class{}
	for _, c := range classes {
		byEmail[c.Email] = c
	}
	if byEmail["user-a"].Minor == 0 || byEmail["user-a"].Minor == byEmail["user-b"].Minor {
		t.Fatalf("classes: %+v", classes)
	}
	if len(byEmail["user-a"].IPs) != 2 {
		t.Fatalf("both public addresses share user-a: %+v", byEmail["user-a"])
	}
	again, ids2 := Assign(shaped, ids)
	if ids2["user-a"] != ids["user-a"] || again[0].Minor == 0 {
		t.Fatalf("class minor must stay put: %v -> %v", ids, ids2)
	}
}
