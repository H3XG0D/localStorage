// AmneziaGoBridge.swift — C API surface for amneziawg-apple WireGuardKitGo.
//
// Real symbols come from linking WireGuardKitGo (amneziawg-apple **v2.0.3**,
// amneziawg-go pin v0.2.19 — not master/v3). See scripts/wizard-apple-native.sh.
// Until that library is linked into the Packet Tunnel target, [isLinked] is false
// and start completes as NE-settings-only (same graceful path as Android without libwg-go.so).
import Foundation

enum AmneziaGoBridge {
    /// Flip to true when WireGuardKitGo is linked and `wgTurnOn` is available.
    /// Product builds set this via compiling with `-DFOCUSVPN_AWG_GO=1` after adding
    /// the amneziawg-apple v2.0.3 go bridge External Build target (see README).
    static var isLinked: Bool { linkedProbe() }

    static func turnOn(settings: String, tunFd: Int32) -> Int32 {
        #if FOCUSVPN_AWG_GO
        return settings.withCString { wgTurnOn($0, tunFd) }
        #else
        _ = settings
        _ = tunFd
        return -1
        #endif
    }

    static func turnOff(_ handle: Int32) {
        #if FOCUSVPN_AWG_GO
        wgTurnOff(handle)
        #else
        _ = handle
        #endif
    }

    static func version() -> String {
        #if FOCUSVPN_AWG_GO
        guard let ver = wgVersion() else { return "unknown" }
        defer { free(UnsafeMutableRawPointer(mutating: ver)) }
        return String(cString: ver)
        #else
        return "unlinked"
        #endif
    }

    private static func linkedProbe() -> Bool {
        #if FOCUSVPN_AWG_GO
        return true
        #else
        return false
        #endif
    }
}

#if FOCUSVPN_AWG_GO
@_silgen_name("wgTurnOn")
func wgTurnOn(_ settings: UnsafePointer<CChar>?, _ tunFd: Int32) -> Int32

@_silgen_name("wgTurnOff")
func wgTurnOff(_ handle: Int32)

@_silgen_name("wgVersion")
func wgVersion() -> UnsafePointer<CChar>?
#endif
