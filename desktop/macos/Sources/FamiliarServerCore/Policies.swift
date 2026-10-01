import Foundation

/// When to restart a server that exited (ADR-0136 point 3).
///
/// Exponential from one second, capped at a minute, and forgiven once a run has lasted long enough
/// to count as healthy. A server that dies at startup, such as one refusing a writable library,
/// must not be restarted in a tight loop, and one that crashed after a week must come back at once.
public struct RestartPolicy: Equatable, Sendable {
    public var consecutiveFailures = 0
    public static let healthyUptime: TimeInterval = 60
    public static let maximumDelay: TimeInterval = 60

    public init() {}

    /// Record an exit after `uptime`, and return how long to wait before starting again.
    public mutating func delay(afterExitWithUptime uptime: TimeInterval) -> TimeInterval {
        if uptime >= Self.healthyUptime { consecutiveFailures = 0 }
        let delay = min(pow(2, Double(consecutiveFailures)), Self.maximumDelay)
        consecutiveFailures += 1
        return delay
    }
}

/// What the machine is doing, as far as ADR-0138 cares.
public struct MachineState: Equatable, Sendable {
    public enum Thermal: Int, Comparable, Sendable {
        case nominal, fair, serious, critical
        public static func < (a: Thermal, b: Thermal) -> Bool { a.rawValue < b.rawValue }
    }

    public var onBattery = false
    public var lowPowerMode = false
    public var thermal: Thermal = .nominal
    /// "Pause Analysis" from the menu.
    public var pausedByOwner = false
    /// "Analyse anyway" until this time; expires by itself (ADR-0138 point 2).
    public var overrideUntil: Date?

    public init(
        onBattery: Bool = false,
        lowPowerMode: Bool = false,
        thermal: Thermal = .nominal,
        pausedByOwner: Bool = false,
        overrideUntil: Date? = nil
    ) {
        self.onBattery = onBattery
        self.lowPowerMode = lowPowerMode
        self.thermal = thermal
        self.pausedByOwner = pausedByOwner
        self.overrideUntil = overrideUntil
    }
}

/// ADR-0138 point 2: whether background work should run, and if not, the reason the menu shows.
public enum Etiquette {
    public enum Decision: Equatable, Sendable {
        case run
        case pause(reason: String)

        public var reason: String? {
            if case .pause(let reason) = self { return reason }
            return nil
        }
    }

    public static func decide(_ state: MachineState, now: Date = Date()) -> Decision {
        // The owner's own pause always wins, and their override never un-pauses it.
        if state.pausedByOwner { return .pause(reason: "Paused by you") }
        if let until = state.overrideUntil, until > now { return .run }
        // Heat first: it is the one that hurts the machine, not just the battery.
        if state.thermal >= .serious { return .pause(reason: "Your Mac is running hot") }
        if state.lowPowerMode { return .pause(reason: "Low Power Mode") }
        if state.onBattery { return .pause(reason: "On battery") }
        return .run
    }
}

/// ADR-0136 point 10: request a sync a while after the library stops changing, not per file.
///
/// Copying an album into the folder is dozens of events in a few seconds. A sync per event would be
/// dozens of syncs; this waits until the folder has been quiet for `quietPeriod`.
public struct SyncDebouncer: Equatable, Sendable {
    public let quietPeriod: TimeInterval
    public private(set) var lastChange: Date?

    public init(quietPeriod: TimeInterval = 180) {
        self.quietPeriod = quietPeriod
    }

    public mutating func noteChange(at date: Date) {
        lastChange = date
    }

    /// Whether a sync is due now. Calling it when due consumes the change.
    public mutating func takeDue(at now: Date) -> Bool {
        guard let last = lastChange, now.timeIntervalSince(last) >= quietPeriod else { return false }
        lastChange = nil
        return true
    }
}

/// The `familiar://pair` link Familiar Server opens for the player on this Mac (ADR-0134 point 5).
///
/// Encoded the way the web admin encodes it (`URLSearchParams`), which the player's `PairingLink`
/// is tested against: a space may arrive as `+` or `%20`, and a literal `+` must be `%2B`.
public enum PairingLinkBuilder {
    public static func link(serverID: String, name: String, host: String, port: Int, token: String) -> URL {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        func encode(_ value: String) -> String {
            value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
        }
        let query = [
            ("id", serverID), ("name", name), ("host", host), ("port", String(port)), ("token", token),
        ].map { "\($0)=\(encode($1))" }.joined(separator: "&")
        return URL(string: "familiar://pair?\(query)")!
    }
}

/// Whether this build looks for updates (ADR-0135 point 3). Only a release does: a development or
/// integration build ("dev", "integration") has no place in the feed, and its first check would put
/// Sparkle's dialog on the desktop of whoever is running the integration check.
public enum UpdatePolicy {
    /// The feed the release job publishes on the `appcast` branch (`scripts/appcast.py`).
    public static let feedURL = URL(string: "https://raw.githubusercontent.com/seethroughlab/familiar/appcast/appcast.xml")!

    public static func checksForUpdates(version: String) -> Bool {
        guard let first = version.unicodeScalars.first else { return false }
        return CharacterSet.decimalDigits.contains(first)
    }
}

/// Where to get the player, for the menu's first-run links (ADR-0135 point 5). One App Store record
/// serves the Mac and the phone; the site's install section links the same id.
public enum PlayerLinks {
    public static let appStoreID = "6759879772"
    /// The Mac App Store app itself, not a web page that offers to open it.
    public static let mac = URL(string: "macappstore://apps.apple.com/app/id\(appStoreID)")!
    /// A web page: a phone app cannot be installed from a Mac, but the page can be shared to one.
    public static let iPhone = URL(string: "https://apps.apple.com/us/app/familiar-player/id\(appStoreID)")!
}

/// What a failed `SMAppService.register()` of the Postgres agent means (ADR-0136 point 4).
///
/// Waiting for the owner's approval is not a failure, but `register()` reports it by throwing, and
/// what was first seen on a real desktop was "Operation not permitted": the app showed "Could not
/// start the database" where it should have offered System Settings. ServiceManagement documents
/// `kSMErrorLaunchDeniedByUser` for this, while the text read as POSIX `EPERM`, so each sign counts.
public enum AgentRegistration: Equatable, Sendable {
    case needsApproval
    case alreadyRegistered
    case failed

    /// `kSMErrorLaunchDeniedByUser` and `kSMErrorAlreadyRegistered` (SMErrors.h: an enum from
    /// `kSMErrorInternalFailure = 2`).
    static let launchDeniedByUser = 11
    static let alreadyRegisteredCode = 12

    public static func outcome(domain: String, code: Int, statusRequiresApproval: Bool) -> AgentRegistration {
        if statusRequiresApproval { return .needsApproval }
        if domain == NSPOSIXErrorDomain && code == Int(EPERM) { return .needsApproval }
        if code == launchDeniedByUser { return .needsApproval }
        if code == alreadyRegisteredCode { return .alreadyRegistered }
        return .failed
    }
}
