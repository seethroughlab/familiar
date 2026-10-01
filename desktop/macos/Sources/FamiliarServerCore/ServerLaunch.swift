import Foundation

/// How the Python server is started: `python -m app.serve` (ADR-0132 point 6) with the environment
/// Familiar Server owes it, under the Seatbelt profile that keeps the music unwritten (ADR-0140).
public struct ServerLaunch: Equatable, Sendable {
    public static let defaultPort = 4400

    /// Deprecated by Apple and still shipped. Without it the server is not started (ADR-0140 point 4).
    public static let sandboxExec = URL(fileURLWithPath: "/usr/bin/sandbox-exec")

    /// Everything allowed but writing the music folder (ADR-0140 point 2). It binds every process the
    /// server starts, and it is what makes `os.access(music, W_OK)` False, so the backend's
    /// zero-touch preflight refuses to start without it (point 3). Measured 2026-10-01: create,
    /// append, rename and mkdir all `EPERM`, from a spawned pool worker and from ffmpeg as well.
    public static let zeroTouchProfile = """
        (version 1)
        (allow default)
        (deny file-write* (subpath (param "MUSIC")))
        """

    public let executable: URL
    public let arguments: [String]
    public let workingDirectory: URL
    public let environment: [String: String]

    /// - Parameters:
    ///   - musicFolder: The folder the owner chose. Its symlinks are resolved for the profile, which
    ///     matches real paths: a folder under `/tmp` is really under `/private/tmp`.
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
        executable = Self.sandboxExec
        arguments = [
            "-p", Self.zeroTouchProfile,
            "-D", "MUSIC=\(musicFolder.resolvingSymlinksInPath().path)",
            layout.python.path, "-m", "app.serve", "--host", lan ? "0.0.0.0" : "127.0.0.1", "--port", String(port),
        ]
        workingDirectory = layout.backend

        var env: [String: String] = [:]
        for key in ["HOME", "TMPDIR", "USER", "LANG", "APP_SANDBOX_CONTAINER_ID"] {
            if let value = inherited[key] { env[key] = value }
        }
        env["PATH"] = [layout.bin.path, "/usr/bin", "/bin"].joined(separator: ":")
        env["DATABASE_URL"] = PostgresSetup.databaseURL(password: databasePassword)
        env["FAMILIAR_DATA_DIR"] = layout.serverData.path
        env["MUSIC_LIBRARY_PATH"] = musicFolder.path
        // AcoustID fingerprints through the same library the Docker image uses, not `fpcalc`: the
        // community cache keys on the result (`analysis._FINGERPRINT_CHILD`).
        env["FAMILIAR_CHROMAPRINT_LIBRARY"] = layout.chromaprintLibrary.path
        // ADR-0138 point 4: one analysis worker on a machine someone is using.
        env["MAX_ANALYSIS_WORKERS"] = "1"
        // Hugging Face's cache (the CLAP tokenizer) inside the container, not the user's home.
        env["HF_HOME"] = layout.serverData.appendingPathComponent("huggingface").path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        environment = env
    }
}
