import AppKit
import FamiliarServerCore
import Foundation
import os
import ServiceManagement

/// Runs the server on this Mac: Postgres through its launch agent, the Python server as a sandboxed
/// child, restarted when it exits, and paused when the machine needs it to be (ADR-0136, ADR-0138).
@MainActor
final class ServerController: ObservableObject {
    enum Status: Equatable {
        case needsFolder
        case needsApproval  // the Postgres agent is waiting in System Settings → Login Items
        case starting(String)
        case running
        case restarting(after: TimeInterval)
        case failed(String)
    }

    /// Every change is logged, so where the app stopped can be read without its menu:
    /// `log show --predicate 'subsystem == "com.familiar.server"'`. The first real install stopped at
    /// "Operation not permitted", and the reason was only on screen.
    @Published private(set) var status: Status = .starting("Starting…") {
        didSet { Self.log.notice("status: \(String(describing: self.status), privacy: .public)") }
    }
    private static let log = Logger(subsystem: Identity.bundleID, category: "lifecycle")
    @Published private(set) var pauseReason: String?
    @Published private(set) var musicFolder: URL?
    @Published var lanEnabled: Bool = UserDefaults.standard.bool(forKey: "lanEnabled") {
        didSet {
            UserDefaults.standard.set(lanEnabled, forKey: "lanEnabled")
            restartServer()
        }
    }

    let layout: Layout
    private var process: Process?
    private var startedAt = Date()
    private var restartPolicy = RestartPolicy()
    private var stopping = false
    private var monitor: MachineMonitor?
    private var lastDecision: Etiquette.Decision = .run
    private(set) var token: String? = TokenStore.load()

    private static let agent = SMAppService.agent(plistName: Identity.postgresAgentPlist)

    // Debug builds only: run the whole bring-up without the folder picker or a Login Items approval,
    // for the integration check (`scripts/integration-check.sh`). Compiled out of release builds.
    #if DEBUG
    private let devMusicFolder = ProcessInfo.processInfo.environment["FAMILIAR_SERVER_DEV_MUSIC"]
        .map { URL(fileURLWithPath: $0) }
    private let devExternalPostgres = ProcessInfo.processInfo.environment["FAMILIAR_SERVER_DEV_EXTERNAL_POSTGRES"] == "1"
    /// Unregister the Postgres agent and quit. The integration check's cleanup: a registered agent
    /// would otherwise start again at the next login, from the build folder.
    private let devUnregister = ProcessInfo.processInfo.environment["FAMILIAR_SERVER_DEV_UNREGISTER"] == "1"
    #else
    private let devUnregister = false
    private let devMusicFolder: URL? = nil
    private let devExternalPostgres = false
    #endif

    init() {
        if devUnregister {
            try? Self.agent.unregister()
            try? SMAppService.mainApp.unregister()
            exit(0)
        }
        layout = Layout(
            appSupport: Layout.defaultAppSupport(bundleID: Bundle.main.bundleIdentifier ?? Identity.bundleID),
            resources: Bundle.main.resourceURL!
        )
        monitor = MachineMonitor { [weak self] state in self?.apply(Etiquette.decide(state)) }
        // However the app ends — its own Quit, a quit from the Dock or another app, logout, restart
        // — the server ends with it. Only the menu's Quit stopped it, so any other way out left
        // Python running with no parent and port 4400 held, and the next launch could not start.
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.stopServer() }
        }
        // At launch, not when the menu is first opened: a menu-style MenuBarExtra builds its
        // contents only on click, so a start hung on the menu would wait for someone to open it,
        // which at login is no one. Found by scripts/integration-check.sh.
        Task { @MainActor in self.start() }
    }

    // MARK: - Lifecycle

    func start() {
        guard let folder = devMusicFolder ?? musicFolder ?? MusicFolder.resolve() else {
            status = .needsFolder
            return
        }
        musicFolder = folder
        stopping = false
        Task { await bringUp(folder: folder) }
    }

    func chooseFolder() {
        guard let folder = MusicFolder.choose() else { return }
        musicFolder = nil
        stopServer()
        musicFolder = folder
        start()
    }

    private func bringUp(folder: URL) async {
        // ADR-0140 point 4: without the profile nothing keeps the music unwritten, so no server.
        guard FileManager.default.isExecutableFile(atPath: ServerLaunch.sandboxExec.path) else {
            status = .failed("This Mac has no sandbox-exec, which keeps your music read-only. Familiar Server will not run without it.")
            return
        }
        do {
            try FileManager.default.createDirectory(at: layout.serverData, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(
                at: layout.postgresPasswordFile.deletingLastPathComponent(), withIntermediateDirectories: true
            )
            if !FileManager.default.fileExists(atPath: layout.postgresPasswordFile.path) {
                FileManager.default.createFile(
                    atPath: layout.postgresPasswordFile.path,
                    contents: Data(PostgresSetup.generatePassword().utf8),
                    attributes: [.posixPermissions: 0o600]
                )
            }
        } catch {
            status = .failed("Could not prepare its folders: \(error.localizedDescription)")
            return
        }

        status = .starting("Starting the database…")
        if !devExternalPostgres {
            do {
                if Self.agent.status != .enabled { try Self.agent.register() }
            } catch {
                let nsError = error as NSError
                switch AgentRegistration.outcome(
                    domain: nsError.domain, code: nsError.code,
                    statusRequiresApproval: Self.agent.status == .requiresApproval
                ) {
                case .needsApproval:
                    status = .needsApproval
                    return
                case .alreadyRegistered:
                    break
                case .failed:
                    status = .failed("Could not start the database: \(error.localizedDescription) (\(nsError.domain) \(nsError.code))")
                    return
                }
            }
            if Self.agent.status == .requiresApproval {
                status = .needsApproval
                return
            }
        }
        guard await waitForPort(PostgresSetup.port, seconds: 60) else {
            status = .failed("The database did not start. Its log is postgres/postgres.log in ~/Library/Application Support/Familiar Server.")
            return
        }

        // New music is the server's to notice now (ADR-0142): it watches the folder itself, as a Docker
        // server does, and scans what changed. This app's FSEvents watch and debouncer were removed.
        launchServer()
    }

    private func launchServer() {
        guard let folder = musicFolder,
              let password = try? String(contentsOf: layout.postgresPasswordFile, encoding: .utf8)
        else { return }
        // A LAN bind needs a token (ADR-0134 point 2); without one, loopback only.
        let launch = ServerLaunch(
            layout: layout, musicFolder: folder,
            databasePassword: password.trimmingCharacters(in: .whitespacesAndNewlines),
            lan: lanEnabled && token != nil,
            inherited: ProcessInfo.processInfo.environment
        )
        let p = Process()
        p.executableURL = launch.executable
        p.arguments = launch.arguments
        p.currentDirectoryURL = launch.workingDirectory
        p.environment = launch.environment
        FileManager.default.createFile(atPath: layout.serverLog.path, contents: nil)
        if let log = try? FileHandle(forWritingTo: layout.serverLog) {
            p.standardOutput = log
            p.standardError = log
        }
        p.terminationHandler = { [weak self] _ in
            Task { @MainActor in self?.serverExited() }
        }
        do {
            try p.run()
        } catch {
            status = .failed("Could not start the server: \(error.localizedDescription)")
            return
        }
        process = p
        startedAt = Date()
        status = .starting("Starting the server…")
        Task { await afterLaunch() }
    }

    private func afterLaunch() async {
        var client = ServerClient()
        for _ in 0..<120 {
            if await client.isHealthy() { break }
            try? await Task.sleep(for: .seconds(1))
        }
        guard await client.isHealthy() else { return }  // the termination handler reports failures
        // Mint the token over loopback, before anything could listen on the network, whenever the
        // *server* has none, whatever this app remembers. A Keychain item outlives the server's
        // settings (a reset, a deleted container), and trusting it would leave a server with no token
        // and an app presenting one it never had. Found by scripts/integration-check.sh.
        client.token = token
        switch try? await client.tokenConfigured() {
        case false?:
            if let minted = try? await client.mintToken() {
                TokenStore.save(minted)
                token = minted
            }
        case true?:
            break  // configured, and our stored token was accepted to learn it
        case nil:
            // Configured, and our token refused (or none stored). Nothing here can recover it:
            // the web admin can rotate it, with the old one, or the server's settings be reset.
            status = .failed("The server has a token this app does not hold. Rotate it in Server → Access.")
            return
        }
        client.token = token
        status = .running
        restartPolicy = RestartPolicy()
        // Re-apply the current etiquette to a freshly started server.
        if let reason = pauseReason { try? await client.pause(reason: reason) }
    }

    private func serverExited() {
        process = nil
        guard !stopping else { return }
        let delay = restartPolicy.delay(afterExitWithUptime: Date().timeIntervalSince(startedAt))
        status = .restarting(after: delay)
        Task {
            try? await Task.sleep(for: .seconds(delay))
            if !stopping { launchServer() }
        }
    }

    func stopServer() {
        stopping = true
        guard let p = process, p.isRunning else { return }
        p.terminate()  // SIGTERM; uvicorn shuts down and cancels in-flight fetches
        let deadline = Date().addingTimeInterval(15)
        while p.isRunning && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.1)) }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }

    private func restartServer() {
        guard process != nil else { return }
        stopServer()
        stopping = false
        launchServer()
    }

    func quit() {
        stopServer()
        // Stop Postgres too: quitting Familiar Server stops the server until the next login.
        try? Self.agent.unregister()
        NSApp.terminate(nil)
    }

    // MARK: - Etiquette (ADR-0138)

    private func apply(_ decision: Etiquette.Decision) {
        guard decision != lastDecision else { return }
        lastDecision = decision
        pauseReason = decision.reason
        let client = ServerClient(token: token)
        Task {
            if let reason = decision.reason { try? await client.pause(reason: reason) }
            else { try? await client.resume() }
        }
    }

    func setPausedByOwner(_ paused: Bool) {
        monitor?.update { $0.pausedByOwner = paused }
    }

    var pausedByOwner: Bool { monitor?.state.pausedByOwner ?? false }

    func analyseAnywayForAnHour() {
        monitor?.update { $0.overrideUntil = Date().addingTimeInterval(3600) }
        // Nothing announces the override's end, so check again once it has passed.
        Timer.scheduledTimer(withTimeInterval: 3601, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.monitor?.refresh() }
        }
    }

    // MARK: - The menu's links

    /// Whether a player is here to receive the pairing link: some app must handle `familiar://`.
    /// Asked each time the menu is drawn, so installing the player changes the menu without a restart.
    var playerInstalled: Bool {
        NSWorkspace.shared.urlForApplication(toOpen: URL(string: "familiar://pair")!) != nil
    }

    func getPlayer(for platform: PlayerPlatform) {
        NSWorkspace.shared.open(platform == .mac ? PlayerLinks.mac : PlayerLinks.iPhone)
    }

    enum PlayerPlatform { case mac, iPhone }

    /// The player on this Mac, paired through the same link a phone scans (ADR-0134 point 5).
    /// With no player to open it, the link would go nowhere and the button would do nothing, so it
    /// goes to the App Store instead.
    func openInFamiliar() {
        guard let token else { return }
        Task {
            let contract = try? await ServerClient(token: token).contract()
            guard let id = contract?.serverID else { return }
            let url = PairingLinkBuilder.link(
                serverID: id, name: contract?.serverName ?? Host.current().localizedName ?? "This Mac",
                host: "127.0.0.1", port: ServerLaunch.defaultPort, token: token
            )
            if !NSWorkspace.shared.open(url) { getPlayer(for: .mac) }
        }
    }

    /// The web admin, handed the token in the fragment (ADR-0134 point 6).
    func openAdmin(path: String = "") {
        var components = URLComponents(string: "http://127.0.0.1:\(ServerLaunch.defaultPort)/\(path)")!
        if let token {
            var fragment = URLComponents()
            fragment.queryItems = [URLQueryItem(name: "token", value: token)]
            components.percentEncodedFragment = fragment.percentEncodedQuery
        }
        if let url = components.url { NSWorkspace.shared.open(url) }
    }

    func openLoginItemsSettings() {
        SMAppService.openSystemSettingsLoginItems()
    }

    // MARK: -

    private func waitForPort(_ port: Int, seconds: Int) async -> Bool {
        for _ in 0..<(seconds * 2) {
            if Self.portOpen(port) { return true }
            try? await Task.sleep(for: .milliseconds(500))
        }
        return false
    }

    private nonisolated static func portOpen(_ port: Int) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(UInt16(port).bigEndian)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        return withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }
}
