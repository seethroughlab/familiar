// swift-tools-version: 6.0
// Familiar Server: the macOS form of the Familiar server (ADR-0131 point 2, ADR-0135, ADR-0136).
//
// A Swift package rather than an Xcode project (ADR-0136 point 7). `scripts/build-app.sh` assembles
// the executables below and the Python/Postgres payload into `Familiar Server.app`.
import PackageDescription

let package = Package(
    name: "FamiliarServer",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "FamiliarServer", targets: ["FamiliarServer"]),
        .executable(name: "familiar-postgres-agent", targets: ["familiar-postgres-agent"]),
    ],
    targets: [
        // Every decision the app makes, where `swift test` can reach it without a GUI.
        .target(name: "FamiliarServerCore"),
        // The menu-bar app: sandboxed, read-only music, supervises the Python server.
        .executableTarget(name: "FamiliarServer", dependencies: ["FamiliarServerCore"]),
        // The Postgres launch agent: unsandboxed (ADR-0136 point 4), initialises then becomes postgres.
        .executableTarget(name: "familiar-postgres-agent", dependencies: ["FamiliarServerCore"]),
        .testTarget(name: "FamiliarServerCoreTests", dependencies: ["FamiliarServerCore"]),
    ]
)
