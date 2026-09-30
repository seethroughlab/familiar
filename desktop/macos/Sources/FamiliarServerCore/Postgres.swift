import Foundation

/// How Postgres is initialised and run beside the sandbox (ADR-0136 point 4).
///
/// Loopback TCP only, and no Unix socket: the agent and the sandboxed server share no directory
/// a socket could live in, and TCP on `127.0.0.1` is something both may use. SCRAM with a random
/// password, because a Mac can have other user accounts and `trust` on loopback would let any of
/// them read this library's database.
public enum PostgresSetup {
    public static let port = 54_329
    public static let user = "familiar"
    public static let database = "familiar"

    /// `initdb` for a fresh data directory. The password file is read once and never stored in the
    /// cluster in the clear.
    public static func initdbArguments(dataDirectory: URL, passwordFile: URL) -> [String] {
        [
            "-D", dataDirectory.path,
            "-U", user,
            "--auth=scram-sha-256",
            "--pwfile=\(passwordFile.path)",
            "--encoding=UTF8",
            "--locale=C",
        ]
    }

    /// The postmaster's arguments. `listen_addresses` is loopback: the agent is not sandboxed, and
    /// nothing but the server on this Mac should ever reach this database.
    public static func serverArguments(dataDirectory: URL) -> [String] {
        [
            "-D", dataDirectory.path,
            "-c", "listen_addresses=127.0.0.1",
            "-c", "port=\(port)",
            "-c", "unix_socket_directories=",
        ]
    }

    /// What the server connects with. Percent-encoded, because a generated password may carry
    /// characters a URL would misread.
    public static func databaseURL(password: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        let encoded = password.addingPercentEncoding(withAllowedCharacters: allowed) ?? password
        return "postgresql+asyncpg://\(user):\(encoded)@127.0.0.1:\(port)/\(database)"
    }

    /// A fresh password: 32 random bytes, URL-safe base64.
    public static func generatePassword() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
