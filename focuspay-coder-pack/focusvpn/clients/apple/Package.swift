// swift-tools-version: 5.9
import PackageDescription

/// Host-side check for ConfigParts parsing (no Apple UI / NE).
/// Full app + Packet Tunnel: `xcodegen generate` + Xcode (see README).
let package = Package(
    name: "FocusVPNAppleShared",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
    ],
    products: [
        .library(name: "FocusVPNConfigParts", targets: ["FocusVPNConfigParts"]),
    ],
    targets: [
        .target(
            name: "FocusVPNConfigParts",
            path: "Sources/Shared",
            sources: ["ConfigPartsParse.swift", "Models.swift", "TunnelConfig.swift", "AwgConfig.swift"]
        ),
        .testTarget(
            name: "FocusVPNConfigPartsTests",
            dependencies: ["FocusVPNConfigParts"],
            path: "TestsSPM"
        ),
    ]
)
