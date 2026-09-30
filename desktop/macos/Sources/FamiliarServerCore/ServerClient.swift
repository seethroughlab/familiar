import Foundation

/// The few calls Familiar Server makes to the server it runs, always over loopback.
///
/// Deliberately not the generated client the player uses (`familiar-apple`'s `FamiliarAPI`): six
/// small calls do not justify a second copy of the schema in this repository, and every one of them
/// is covered by the backend's own tests.
public struct ServerClient: Sendable {
    public let baseURL: URL
    public var token: String?
    let session: URLSession

    public init(port: Int = ServerLaunch.defaultPort, token: String? = nil, session: URLSession = .shared) {
        self.baseURL = URL(string: "http://127.0.0.1:\(port)")!
        self.token = token
        self.session = session
    }

    public struct Contract: Decodable, Equatable, Sendable {
        public let serverID: String?
        public let serverName: String?
        enum CodingKeys: String, CodingKey {
            case serverID = "server_id"
            case serverName = "server_name"
        }
    }

    public enum Failure: Error, Equatable {
        case status(Int)
        case malformed
    }

    func request(_ path: String, method: String = "GET", json: [String: String]? = nil) -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent(path), timeoutInterval: 10)
        request.httpMethod = method
        if let token { request.setValue(token, forHTTPHeaderField: "X-Familiar-Token") }
        if let json {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: json)
        }
        return request
    }

    @discardableResult
    func send(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw Failure.status(status) }
        return data
    }

    /// Up and answering. Never throws: a server that is not up is `false`.
    public func isHealthy() async -> Bool {
        (try? await send(request("api/v1/health"))) != nil
    }

    public func contract() async throws -> Contract {
        try JSONDecoder().decode(Contract.self, from: try await send(request("api/v1/contract")))
    }

    /// Mint the server's token (`POST /api/v1/auth/token`). On a server without one, anything on
    /// loopback may; Familiar Server does it on first run, before anything listens on the network.
    public func mintToken() async throws -> String {
        let data = try await send(request("api/v1/auth/token", method: "POST"))
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let token = object["token"] as? String
        else { throw Failure.malformed }
        return token
    }

    /// Whether the server has a token already (it may, from a previous run).
    public func tokenConfigured() async throws -> Bool {
        let data = try await send(request("api/v1/auth/token"))
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return object?["configured"] as? Bool ?? false
    }

    public func pause(reason: String) async throws {
        try await send(request("api/v1/background/pause", method: "POST", json: ["reason": reason]))
    }

    public func resume() async throws {
        try await send(request("api/v1/background/resume", method: "POST"))
    }

    /// Start a library sync, as the folder watch does when new music arrives (ADR-0136 point 10).
    public func startSync() async throws {
        try await send(request("api/v1/library/sync", method: "POST", json: [:]))
    }
}
