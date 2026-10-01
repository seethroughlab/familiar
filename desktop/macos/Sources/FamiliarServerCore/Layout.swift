import Foundation

/// The identifiers that tie the app and its agent together (ADR-0136, ADR-0140).
public enum Identity {
    public static let bundleID = "com.familiar.server"
    /// Names the folder that holds Postgres's data, `~/Library/Group Containers/7JL9RZ9C8P.fs`. It
    /// was an App Sandbox group, short so that semaphore names fit under it (ADR-0136 point 3);
    /// with no sandbox (ADR-0140) it is only a path, kept so that nothing already there moves.
    public static let appGroup = "7JL9RZ9C8P.fs"
    /// The launch agent that runs Postgres beside the sandbox (ADR-0136 point 4).
    public static let postgresAgentLabel = "com.familiar.server.postgres"
    public static let postgresAgentPlist = postgresAgentLabel + ".plist"
}

/// Where everything lives on disk.
///
/// Postgres's data and password live in the **app group container**, because two processes need
/// them: the unsandboxed agent that runs Postgres, and the sandboxed server that connects to it.
/// Both are group members, so neither needs the other's container and no Keychain item is shared.
/// The server's own state (`FAMILIAR_DATA_DIR`) stays in the app's container.
public struct Layout: Sendable, Equatable {
    public let groupContainer: URL
    public let appSupport: URL
    public let resources: URL

    public init(groupContainer: URL, appSupport: URL, resources: URL) {
        self.groupContainer = groupContainer
        self.appSupport = appSupport
        self.resources = resources
    }

    // Shared with the agent.
    public var postgresData: URL { groupContainer.appendingPathComponent("postgres/data") }
    public var postgresPasswordFile: URL { groupContainer.appendingPathComponent("postgres/password") }
    public var postgresLog: URL { groupContainer.appendingPathComponent("postgres/postgres.log") }

    // The server's own.
    public var serverData: URL { appSupport.appendingPathComponent("data") }
    public var serverLog: URL { appSupport.appendingPathComponent("server.log") }

    // The payload inside the bundle.
    public var python: URL { resources.appendingPathComponent("python/bin/python3") }
    public var backend: URL { resources.appendingPathComponent("backend") }
    public var bin: URL { resources.appendingPathComponent("bin") }
    /// On no search path, so the server is told where it is (`FAMILIAR_CHROMAPRINT_LIBRARY`).
    public var chromaprintLibrary: URL { resources.appendingPathComponent("lib/libchromaprint.1.dylib") }
    public var postgresBin: URL { resources.appendingPathComponent("postgres/bin") }
}
