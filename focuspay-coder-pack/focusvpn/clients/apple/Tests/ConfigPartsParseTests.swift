import XCTest
@testable import FocusVPN

final class ConfigPartsParseTests: XCTestCase {
    func testExtractsJcJminJmaxAndEndpoint() throws {
        let json = """
        {
          "protocol": {
            "name": "amneziawg",
            "obfuscation": {
              "junk_packet_count": 7,
              "junk_min_size": 10,
              "junk_max_size": 50
            }
          },
          "peer": { "endpoint": "203.0.113.10:51820" }
        }
        """.data(using: .utf8)!
        let obj = try JSONSerialization.jsonObject(with: json) as! [String: Any]
        let obf = ConfigPartsParse.obfuscation(from: obj)
        XCTAssertEqual(obf?.junkPacketCount, 7)
        XCTAssertEqual(obf?.junkMinSize, 10)
        XCTAssertEqual(obf?.junkMaxSize, 50)
        XCTAssertEqual(ConfigPartsParse.peerEndpoint(from: obj), "203.0.113.10:51820")
    }

    func testMissingObfuscationReturnsNil() throws {
        let json = #"{"peer":{"endpoint":"x"}}"#.data(using: .utf8)!
        let obj = try JSONSerialization.jsonObject(with: json) as! [String: Any]
        XCTAssertNil(ConfigPartsParse.obfuscation(from: obj))
    }

    func testTunnelConfigFromParts() throws {
        let json = """
        {
          "interface": { "address": "10.200.0.2/32", "dns": ["1.1.1.1"], "mtu": 1420 },
          "peer": {
            "server_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "endpoint": "203.0.113.10:51820",
            "allowed_ips": ["0.0.0.0/0"]
          },
          "protocol": {
            "obfuscation": {
              "junk_packet_count": 4,
              "junk_min_size": 40,
              "junk_max_size": 70
            }
          }
        }
        """.data(using: .utf8)!
        let parts = try JSONSerialization.jsonObject(with: json) as! [String: Any]
        let cfg = try TunnelConfig.fromParts(parts, privateKeyB64: "k")
        XCTAssertEqual(cfg.endpointHost, "203.0.113.10")
        XCTAssertEqual(cfg.jc, 4)
    }

    func testX25519PublicDerivedFromPrivate() throws {
        let keys = X25519Keys.generate()
        let derived = try X25519Keys.publicFromPrivate(privateKeyB64: keys.privB64)
        XCTAssertEqual(keys.pubB64, derived)
        XCTAssertNotEqual(keys.privB64, keys.pubB64)
    }
}
