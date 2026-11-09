package xray

import (
	"bufio"
	"os"
	"path/filepath"
	"strings"
)

// Domain suffixes that leave on the machine's own IP. Same list as Android
// RuDirect — Russian services ban a VPN exit.
var ruDomainSuffixes = []string{
	"ru",
	"su",
	"xn--p1ai",
	"moscow",
	"tatar",
	"yandex.net",
	"yandex.com",
	"yandex.cloud",
	"yastatic.net",
	"yandexcloud.net",
	"vk.com",
	"vk.me",
	"userapi.com",
	"vkuser.net",
	"vk-portal.net",
	"mycdn.me",
	"2gis.com",
	"avito.st",
	"wbstatic.net",
	"ozonusercontent.com",
	"sberbank.com",
}

var privateCIDRs = []string{
	"0.0.0.0/8",
	"10.0.0.0/8",
	"100.64.0.0/10",
	"127.0.0.0/8",
	"169.254.0.0/16",
	"172.16.0.0/12",
	"192.0.0.0/24",
	"192.0.2.0/24",
	"192.168.0.0/16",
	"198.18.0.0/15",
	"198.51.100.0/24",
	"203.0.113.0/24",
	"224.0.0.0/4",
	"240.0.0.0/4",
	"::1/128",
	"fc00::/7",
	"fe80::/10",
}

func domainRules() []string {
	out := make([]string, len(ruDomainSuffixes))
	for i, s := range ruDomainSuffixes {
		out[i] = "domain:" + s
	}
	return out
}

func ipRules(prefixes []string) []string {
	out := make([]string, 0, len(privateCIDRs)+len(prefixes))
	out = append(out, privateCIDRs...)
	out = append(out, prefixes...)
	return out
}

// LoadRUPrefixes reads the RIPE snapshot Android already ships. The file is not
// copied into this package. Set FOCUSVPN_RU_PREFIXES to point at a checkout
// when the binary is not run from the repo.
func LoadRUPrefixes() ([]string, error) {
	path, err := findRUPrefixes()
	if err != nil {
		return nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var out []string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(strings.SplitN(sc.Text(), "#", 2)[0])
		if line != "" {
			out = append(out, line)
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	if len(out) == 0 {
		return nil, os.ErrNotExist
	}
	return out, nil
}

func findRUPrefixes() (string, error) {
	if p := strings.TrimSpace(os.Getenv("FOCUSVPN_RU_PREFIXES")); p != "" {
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p, nil
		}
	}
	rel := filepath.Join("clients", "android", "app", "src", "main", "assets", "ru-prefixes.txt")
	var starts []string
	if wd, err := os.Getwd(); err == nil {
		starts = append(starts, wd)
	}
	if exe, err := os.Executable(); err == nil {
		starts = append(starts, filepath.Dir(exe))
	}
	for _, start := range starts {
		dir := start
		for i := 0; i < 8; i++ {
			for _, name := range []string{rel, "ru-prefixes.txt"} {
				p := filepath.Join(dir, name)
				if st, err := os.Stat(p); err == nil && !st.IsDir() {
					return p, nil
				}
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	return "", os.ErrNotExist
}
