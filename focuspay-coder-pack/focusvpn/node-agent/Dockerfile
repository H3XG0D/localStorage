# FocusVPN node-agent container image (dev / CI).
# Requires awg and awg-quick from AmneziaWG tools to be available on the host
# or baked in. The image builds the Go binary; awg tools are expected at runtime
# (CAP_NET_ADMIN required).
FROM docker.io/library/golang:1.25-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /node-agent ./node-agent/cmd/agent

FROM docker.io/library/debian:bookworm-slim
# awg/awg-quick are GPL tools installed on the host or as separate packages.
# They are NOT linked into this binary (license compliance, ADR-002).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates iproute2 wireguard-tools && rm -rf /var/lib/apt/lists/*
COPY --from=build /node-agent /usr/local/bin/node-agent
ENTRYPOINT ["/usr/local/bin/node-agent"]
