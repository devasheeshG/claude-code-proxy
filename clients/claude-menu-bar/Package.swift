// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ClaudeMenuBar",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "ClaudeMenuBar", targets: ["ClaudeMenuBar"]),
        .executable(name: "ClaudeMenuBarSnapshot", targets: ["ClaudeMenuBarSnapshot"]),
    ],
    targets: [
        .target(name: "ClaudeMenuBarKit"),
        .executableTarget(name: "ClaudeMenuBar", dependencies: ["ClaudeMenuBarKit"]),
        .executableTarget(name: "ClaudeMenuBarSnapshot", dependencies: ["ClaudeMenuBarKit"]),
    ]
)
