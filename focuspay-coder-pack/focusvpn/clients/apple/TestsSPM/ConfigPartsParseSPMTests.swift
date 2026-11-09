import XCTest
@testable import FocusVPNConfigParts

final class ConfigPartsParseSPMTests: XCTestCase {
    private let fullObf = """
              "junk_packet_count": 7,
              "junk_min_size": 10,
              "junk_max_size": 50,
              "init_packet_junk_size": 15,
              "response_packet_junk_size": 20,
              "cookie_reply_junk_size": 10,
              "transport_packet_junk_size": 5,
              "init_packet_magic_header": "100-110",
              "response_packet_magic_header": "200-210",
              "underload_packet_magic_header": "300-310",
              "transport_packet_magic_header": "400-410",
              "special_junk_i1": "<b 0xde01>"
    """

    func testExtractsJcJminJmaxAndEndpoint() throws {
        let json = """
        {
          "protocol": {
            "obfuscation": {
              \(fullObf)
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
        XCTAssertEqual(obf?.s1, 15)
        XCTAssertEqual(obf?.h1, "100-110")
        XCTAssertEqual(obf?.i1, "<b 0xde01>")
        XCTAssertEqual(ConfigPartsParse.peerEndpoint(from: obj), "203.0.113.10:51820")
    }

    func testTunnelConfigFromPartsAndRoundTrip() throws {
        let json = """
        {
          "interface": {
            "address": "10.200.0.5/32",
            "dns": ["10.200.0.1"],
            "mtu": 1280
          },
          "peer": {
            "server_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "endpoint": "de-01.focusvpn.example:51820",
            "allowed_ips": ["0.0.0.0/0", "::/0"]
          },
          "protocol": {
            "obfuscation": {
              "junk_packet_count": 4,
              "junk_min_size": 40,
              "junk_max_size": 70,
              "init_packet_junk_size": 15,
              "response_packet_junk_size": 20,
              "cookie_reply_junk_size": 10,
              "transport_packet_junk_size": 5,
              "init_packet_magic_header": "100-110",
              "response_packet_magic_header": "200-210",
              "underload_packet_magic_header": "300-310",
              "transport_packet_magic_header": "400-410",
              "special_junk_i1": "<b 0xde01>"
            }
          }
        }
        """.data(using: .utf8)!
        let parts = try JSONSerialization.jsonObject(with: json) as! [String: Any]
        let cfg = try TunnelConfig.fromParts(parts, privateKeyB64: "priv")
        XCTAssertEqual(cfg.addressHost, "10.200.0.5")
        XCTAssertEqual(cfg.addressPrefix, 32)
        XCTAssertEqual(cfg.endpoint, "de-01.focusvpn.example:51820")
        XCTAssertEqual(cfg.jc, 4)
        XCTAssertEqual(cfg.h1, "100-110")
        XCTAssertEqual(cfg.s1, 15)
        XCTAssertEqual(TunnelConfig.ipv4SubnetMask(prefix: 32), "255.255.255.255")
        XCTAssertEqual(TunnelConfig.ipv4SubnetMask(prefix: 24), "255.255.255.0")

        let round = TunnelConfig.fromProviderConfiguration(cfg.asProviderConfiguration())
        XCTAssertEqual(round?.endpoint, cfg.endpoint)
        XCTAssertEqual(round?.privateKeyB64, "priv")
        XCTAssertEqual(round?.jmax, 70)
        XCTAssertEqual(round?.h4, "400-410")
        XCTAssertEqual(round?.i1, "<b 0xde01>")
    }

    func testAwgConfigUapiAndQuick() throws {
        let priv = Data(repeating: 1, count: 32).base64EncodedString()
        let pub = Data(repeating: 2, count: 32).base64EncodedString()
        let cfg = TunnelConfig(
            privateKeyB64: priv,
            serverPublicKeyB64: pub,
            addressCidr: "10.200.0.5/32",
            dns: ["10.200.0.1"],
            mtu: 1420,
            endpoint: "127.0.0.1:51820",
            allowedIps: ["0.0.0.0/0", "::/0"],
            jc: 4,
            jmin: 40,
            jmax: 70,
            s1: 15,
            s2: 20,
            s3: 10,
            s4: 5,
            h1: "100-110",
            h2: "200-210",
            h3: "300-310",
            h4: "400-410",
            i1: "<b 0xde01>",
            i2: "",
            i3: "",
            i4: "",
            i5: ""
        )
        let uapi = try AwgConfig.toUapi(cfg)
        XCTAssertTrue(uapi.contains("jc=4\n"))
        XCTAssertTrue(uapi.contains("s1=15\n"))
        XCTAssertTrue(uapi.contains("h1=100-110\n"))
        XCTAssertTrue(uapi.contains("i1=<b 0xde01>\n"))
        XCTAssertTrue(uapi.contains("replace_peers=true\n"))
        XCTAssertTrue(uapi.contains("endpoint=127.0.0.1:51820\n"))
        let privHex = uapi.split(separator: "\n").first { $0.hasPrefix("private_key=") }!
            .split(separator: "=")[1]
        XCTAssertEqual(privHex.count, 64)

        let quick = try AwgConfig.toAwgQuick(cfg)
        XCTAssertTrue(quick.contains("Jc = 4"))
        XCTAssertTrue(quick.contains("H1 = 100-110"))
        XCTAssertTrue(quick.contains("PrivateKey = \(priv)"))
        XCTAssertTrue(quick.contains("PublicKey = \(pub)"))
    }
}
