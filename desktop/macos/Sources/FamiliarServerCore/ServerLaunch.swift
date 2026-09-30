import Foundation

/// How the Python server is started: `python -m app.serve` (ADR-0132 point 6) with the environment
/// Familiar Server owes it.
public struct ServerLaunch: Equatable, Sendable {
    public static let defaultPort = 4400

    public let executable: URL
    public let arguments: [String]
    public let workingDirectory: URL
    public let environment: [String: String]

    /// - Parameters:
    ///   - musicFolder: The folder the owner chose, resolved from its security-scoped bookmark.
    ///   - lan: Listen beyond loopback. The server refuses that without a token (ADR-0134 point 2),
    ///     so the app only asks for it once one exists.
    ///   - inherited: The app's own environment, filtered: nothing of the developer's shell may
    ///     leak into the server (a stray `REDIS_URL` would switch its store; ADR-0133).
    public init(
        layout: Layout,
        musicFolder: URL,
        databasePassword: String,
        port: Int = ServerLaunch.defaultPort,
        lan: Bool = false,
        inherited: [String: String] = [:]
    ) {
        executable = layout.python
        arguments = ["-m", "app.serve", "--host", lan ? "0.0.0.0" : "127.0.0.1", "--port", String(port)]
        workingDirectory = layout.backend

        var env: [String: String] = [:]
        for key in ["HOME", "TMPDIR", "USER", "LANG", "APP_SANDBOX_CONTAINER_ID"] {
            if let value = inherited[key] { env[key] = value }
        }
        env["PATH"] = [layout.bin.path, "/usr/bin", "/bin"].joined(separator: ":")
        env["DATABASE_URL"] = PostgresSetup.databaseURL(password: databasePassword)
        env["FAMILIAR_DATA_DIR"] = layout.serverData.path
        env["MUSIC_LIBRARY_PATH"] = musicFolder.path
        // ADR-0136 point 3: the sandbox refuses semaphores outside the app group.
        env["FAMILIAR_SEMAPHORE_PREFIX"] = Identity.semaphorePrefix
        // ADR-0138 point 4: one analysis worker on a machine someone is using.
        env["MAX_ANALYSIS_WORKERS"] = "1"
        // Hugging Face's cache (the CLAP tokenizer) inside the container, not the user's home.
        env["HF_HOME"] = layout.serverData.appendingPathComponent("huggingface").path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        environment = env
    }
}
