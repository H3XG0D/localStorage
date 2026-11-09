// AmneziaTunnelEngine.swift — utun FD + amneziawg-go backend (P3-M4c)
import Darwin
import Foundation
import NetworkExtension

/// Starts userspace AmneziaWG after NE network settings are applied.
/// Locates the utun FD (wireguard-apple pattern) and calls WireGuardKitGo when linked.
final class AmneziaTunnelEngine {
    private var handle: Int32 = -1
    private(set) var nativeActive = false
    private(set) var lastError: String?

    func start(cfg: TunnelConfig) {
        stop()
        lastError = nil

        var resolved = cfg
        if let ipEndpoint = Self.resolveEndpointHostToIP(cfg.endpoint) {
            resolved = TunnelConfig(
                privateKeyB64: cfg.privateKeyB64,
                serverPublicKeyB64: cfg.serverPublicKeyB64,
                addressCidr: cfg.addressCidr,
                dns: cfg.dns,
                mtu: cfg.mtu,
                endpoint: ipEndpoint,
                allowedIps: cfg.allowedIps,
                jc: cfg.jc,
                jmin: cfg.jmin,
                jmax: cfg.jmax,
                s1: cfg.s1,
                s2: cfg.s2,
                s3: cfg.s3,
                s4: cfg.s4,
                h1: cfg.h1,
                h2: cfg.h2,
                h3: cfg.h3,
                h4: cfg.h4,
                i1: cfg.i1,
                i2: cfg.i2,
                i3: cfg.i3,
                i4: cfg.i4,
                i5: cfg.i5
            )
        }

        let uapi: String
        do {
            uapi = try AwgConfig.toUapi(resolved)
        } catch {
            lastError = error.localizedDescription
            NSLog("FocusVPN AmneziaTunnelEngine UAPI error: %@", error.localizedDescription)
            return
        }

        guard AmneziaGoBridge.isLinked else {
            lastError = "WireGuardKitGo not linked — NE settings only"
            NSLog("FocusVPN %@", lastError!)
            nativeActive = false
            return
        }

        guard let fd = Self.tunnelFileDescriptor else {
            lastError = "cannot locate utun file descriptor"
            NSLog("FocusVPN %@", lastError!)
            nativeActive = false
            return
        }

        let h = AmneziaGoBridge.turnOn(settings: uapi, tunFd: fd)
        if h < 0 {
            lastError = "wgTurnOn failed code=\(h)"
            NSLog("FocusVPN %@", lastError!)
            nativeActive = false
            return
        }
        handle = h
        nativeActive = true
        NSLog("FocusVPN AmneziaWG up version=%@ handle=%d", AmneziaGoBridge.version(), h)
    }

    func stop() {
        if handle >= 0 {
            AmneziaGoBridge.turnOff(handle)
            handle = -1
        }
        nativeActive = false
    }

    /// Same utun discovery as wireguard-apple / amneziawg-apple WireGuardAdapter (MIT).
    static var tunnelFileDescriptor: Int32? {
        var ctlInfo = ctl_info()
        withUnsafeMutablePointer(to: &ctlInfo.ctl_name) {
            $0.withMemoryRebound(to: CChar.self, capacity: MemoryLayout.size(ofValue: $0.pointee)) {
                _ = strcpy($0, "com.apple.net.utun_control")
            }
        }
        for fd: Int32 in 0...1024 {
            var addr = sockaddr_ctl()
            var ret: Int32 = -1
            var len = socklen_t(MemoryLayout.size(ofValue: addr))
            withUnsafeMutablePointer(to: &addr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    ret = getpeername(fd, $0, &len)
                }
            }
            if ret != 0 || addr.sc_family != AF_SYSTEM {
                continue
            }
            if ctlInfo.ctl_id == 0 {
                ret = ioctl(fd, CTLIOCGINFO, &ctlInfo)
                if ret != 0 {
                    continue
                }
            }
            if addr.sc_id == ctlInfo.ctl_id {
                return fd
            }
        }
        return nil
    }

    /// Prefer numeric host for UAPI (amneziawg-go ParseEndpoint is IP-oriented).
    static func resolveEndpointHostToIP(_ endpoint: String) -> String? {
        let host: String
        let port: String
        if endpoint.hasPrefix("["), let close = endpoint.firstIndex(of: "]") {
            host = String(endpoint[endpoint.index(after: endpoint.startIndex)..<close])
            let rest = endpoint[endpoint.index(after: close)...]
            guard rest.hasPrefix(":"), rest.count > 1 else { return nil }
            port = String(rest.dropFirst())
        } else {
            let parts = endpoint.split(separator: ":", maxSplits: 1)
            guard parts.count == 2 else { return nil }
            host = String(parts[0])
            port = String(parts[1])
        }
        // Already an IPv4 literal.
        if host.split(separator: ".").count == 4, host.allSatisfy({ $0.isNumber || $0 == "." }) {
            return endpoint
        }
        var hints = addrinfo(
            ai_flags: AI_ADDRCONFIG,
            ai_family: AF_INET,
            ai_socktype: SOCK_DGRAM,
            ai_protocol: IPPROTO_UDP,
            ai_addrlen: 0,
            ai_canonname: nil,
            ai_addr: nil,
            ai_next: nil
        )
        var result: UnsafeMutablePointer<addrinfo>?
        let err = getaddrinfo(host, port, &hints, &result)
        defer { if result != nil { freeaddrinfo(result) } }
        guard err == 0, let first = result else { return nil }
        var hostBuf = [CChar](repeating: 0, count: Int(NI_MAXHOST))
        var servBuf = [CChar](repeating: 0, count: Int(NI_MAXSERV))
        let gerr = getnameinfo(
            first.pointee.ai_addr,
            first.pointee.ai_addrlen,
            &hostBuf,
            socklen_t(hostBuf.count),
            &servBuf,
            socklen_t(servBuf.count),
            NI_NUMERICHOST | NI_NUMERICSERV
        )
        guard gerr == 0 else { return nil }
        let ip = String(cString: hostBuf)
        let p = String(cString: servBuf)
        return "\(ip):\(p)"
    }
}
