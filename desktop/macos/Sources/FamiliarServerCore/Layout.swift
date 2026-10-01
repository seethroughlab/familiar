import Foundation

/// The identifiers that tie the app and its agent together (ADR-0136, ADR-0140).
public enum Identity {
    public static let bundleID = "com.familiar.server"
    /// The launch agent that runs Postgres beside the sandbox (ADR-0136 point 4).
    public static let postgresAgentLabel = "com.familiar.server.postgres"
    public static let postgresAgentPlist = postgresAgentLabel + ".plist"
}

/// Where everything lives on disk: one folder, `~/Library/Application Support/Familiar Server`.
///
/// The app and its Postgres agent are both unsandboxed and run as the owner (ADR-0140), so they share
/// it with no container or group between them. Postgres's data was in an app group container while
/// the app was sandboxed; without the group entitlement, writing there asks the owner's permission
/// ("would like to access data from other apps"), and the app waited on that prompt (ADR-0140).
public struct Layout: Sendable, Equatable {
    public let appSupport: URL
    public let resources: URL

    public init(appSupport: URL, resources: URL) {
        self.appSupport = appSupport
        self.resources = resources
    }

    /// The folder for this user, computed the same way by the app and by the agent.
    public static func defaultAppSupport(home: String = NSHomeDirectory()) -> URL {
        URL(fileURLWithPath: home).appendingPathComponent("Library/Application Support/Familiar Server")
    }

    // Postgres's, written by the agent and read by the app.
    public var postgresData: URL { appSupport.appendingPathComponent("postgres/data") }
    public var postgresPasswordFile: URL { appSupport.appendingPathComponent("postgres/password") }
    public var postgresLog: URL { appSupport.appendingPathComponent("postgres/postgres.log") }

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
