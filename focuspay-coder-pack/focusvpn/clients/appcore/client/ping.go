package client

import (
	"net"
	"strconv"
	"time"
)

// TcpPing is the TCP handshake time in milliseconds, or -1 when host:port does not answer.
func TcpPing(host string, port int) int {
	if host == "" || port < 1 || port > 65535 {
		return -1
	}
	start := time.Now()
	c, err := net.DialTimeout("tcp", net.JoinHostPort(host, strconv.Itoa(port)), 2*time.Second)
	if err != nil {
		return -1
	}
	_ = c.Close()
	ms := int(time.Since(start).Milliseconds())
	if ms < 1 {
		ms = 1
	}
	if ms > 60000 {
		ms = 60000
	}
	return ms
}
