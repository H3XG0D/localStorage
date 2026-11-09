package billing

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var rublesRe = regexp.MustCompile(`^[0-9]{1,8}(\.[0-9]{1,2})?$`)

// ParseRubles converts a decimal ruble string ("300", "990.5", "2490.00") to
// kopecks without floating point. Empty means zero.
func ParseRubles(s string) (int64, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, nil
	}
	if !rublesRe.MatchString(s) {
		return 0, fmt.Errorf("billing: invalid amount_rub %q", s)
	}
	whole, frac, _ := strings.Cut(s, ".")
	for len(frac) < 2 {
		frac += "0"
	}
	r, err := strconv.ParseInt(whole, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("billing: invalid amount_rub %q", s)
	}
	k, err := strconv.ParseInt(frac, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("billing: invalid amount_rub %q", s)
	}
	return r*100 + k, nil
}
