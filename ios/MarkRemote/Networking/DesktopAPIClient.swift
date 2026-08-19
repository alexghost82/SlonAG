import Foundation
import MarkRemoteModels

public enum DesktopAPIClientError: Error, Sendable, Equatable {
    case invalidBaseURL(BaseURLPolicyError)
    case invalidResponse
    case httpStatus(Int, APIErrorEnvelope?)
    case decodingFailed
    case encodingFailed
    case missingAccessToken
    case transport(String)
}

/// HTTP client for Desktop Control `/v1` routes.
public final class DesktopAPIClient: @unchecked Sendable {
    public let baseURL: URL
    public let allowNonLoopback: Bool

    private let session: URLSession
    private let tokenProvider: any AccessTokenProviding
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    public init(
        baseURL: URL? = nil,
        host: String = BaseURLPolicy.defaultHost,
        port: Int = BaseURLPolicy.defaultPort,
        allowNonLoopback: Bool = false,
        session: URLSession = .shared,
        tokenProvider: any AccessTokenProviding = StaticAccessTokenProvider(token: nil),
        decoder: JSONDecoder = DesktopAPIJSON.decoder,
        encoder: JSONEncoder = DesktopAPIJSON.encoder
    ) throws {
        self.allowNonLoopback = allowNonLoopback
        self.session = session
        self.tokenProvider = tokenProvider
        self.decoder = decoder
        self.encoder = encoder

        let resolved: URL
        if let baseURL {
            do {
                try BaseURLPolicy.validate(baseURL: baseURL, allowNonLoopback: allowNonLoopback)
            } catch let error as BaseURLPolicyError {
                throw DesktopAPIClientError.invalidBaseURL(error)
            }
            resolved = baseURL
        } else {
            do {
                resolved = try BaseURLPolicy.makeBaseURL(
                    host: host,
                    port: port,
                    allowNonLoopback: allowNonLoopback
                )
            } catch let error as BaseURLPolicyError {
                throw DesktopAPIClientError.invalidBaseURL(error)
            }
        }
        self.baseURL = resolved
    }

    // MARK: - Status

    public func getStatus() async throws -> StatusResponse {
        try await request(method: "GET", path: "/v1/status", body: Optional<EmptyBody>.none, authenticated: true)
    }

    public func controlRuntime(action: String) async throws {
        let _: RuntimeControlResponse = try await request(
            method: "POST",
            path: "/v1/runtime/control",
            body: RuntimeControlRequest(action: action, idempotencyKey: UUID().uuidString),
            authenticated: true
        )
    }

    // MARK: - Pairing

    public func startPairing(_ body: PairingStartRequest) async throws -> PairingStartResponse {
        try await request(method: "POST", path: "/v1/pairing/start", body: body, authenticated: false)
    }

    public func completePairing(_ body: PairingCompleteRequest) async throws -> PairingCompleteResponse {
        try await request(method: "POST", path: "/v1/pairing/complete", body: body, authenticated: false)
    }

    public func revokePairing(_ body: PairingRevokeRequest) async throws -> PairingRevokeResponse {
        try await request(
            method: "POST",
            path: "/v1/pairing/revoke",
            body: body,
            authenticated: true
        )
    }

    // MARK: - Chat

    public func sendChat(_ body: ChatRequest) async throws -> ChatStreamEvent {
        try await request(method: "POST", path: "/v1/chat", body: body, authenticated: true)
    }

    // MARK: - Tasks

    public func listTasks() async throws -> TaskListResponse {
        try await request(method: "GET", path: "/v1/tasks", body: Optional<EmptyBody>.none, authenticated: true)
    }

    public func createTask(_ body: TaskCreateRequest) async throws -> TaskInfo {
        try await request(method: "POST", path: "/v1/tasks", body: body, authenticated: true)
    }

    public func cancelTask(id: String, body: TaskCancelRequest) async throws -> TaskInfo {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        return try await request(
            method: "POST",
            path: "/v1/tasks/\(encoded)/cancel",
            body: body,
            authenticated: true
        )
    }

    // MARK: - Approvals

    public func listApprovals() async throws -> ApprovalListResponse {
        try await request(method: "GET", path: "/v1/approvals", body: Optional<EmptyBody>.none, authenticated: true)
    }

    public func decideApproval(id: String, body: ApprovalDecisionRequest) async throws -> ApprovalInfo {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        return try await request(
            method: "POST",
            path: "/v1/approvals/\(encoded)/decision",
            body: body,
            authenticated: true
        )
    }

    // MARK: - Models

    public func listModels() async throws -> ModelsListResponse {
        try await request(method: "GET", path: "/v1/models", body: Optional<EmptyBody>.none, authenticated: true)
    }

    public func activateModel(_ body: ModelsActivateRequest) async throws -> ModelInfo {
        try await request(method: "POST", path: "/v1/models/activate", body: body, authenticated: true)
    }

    // MARK: - Memory

    public func getMemory() async throws -> MemoryGetResponse {
        try await request(method: "GET", path: "/v1/memory", body: Optional<EmptyBody>.none, authenticated: true)
    }

    public func deleteMemory(id: String, body: MemoryDeleteRequest) async throws {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        let _: EmptyResponse = try await request(
            method: "DELETE",
            path: "/v1/memory/\(encoded)",
            body: body,
            authenticated: true
        )
    }

    // MARK: - Screen

    public func captureScreen(_ body: ScreenCaptureRequest) async throws -> ScreenCaptureResponse {
        try await request(method: "POST", path: "/v1/screen/capture", body: body, authenticated: true)
    }

    public func fetchScreenFrame() async throws -> Data {
        try await requestData(method: "GET", path: "/v1/screen/frame", authenticated: true)
    }

    // MARK: - Files

    public func listFiles(path: String) async throws -> FilesListResponse {
        var components = URLComponents()
        components.path = "/v1/files"
        components.queryItems = [URLQueryItem(name: "path", value: path)]
        guard let route = components.string else {
            throw DesktopAPIClientError.invalidResponse
        }
        return try await request(
            method: "GET",
            path: route,
            body: Optional<EmptyBody>.none,
            authenticated: true
        )
    }

    public func uploadFile(_ body: FileUploadRequest) async throws -> FileUploadResponse {
        try await request(
            method: "POST",
            path: "/v1/files/upload",
            body: body,
            authenticated: true
        )
    }

    // MARK: - Internals

    private struct EmptyBody: Encodable {}
    private struct EmptyResponse: Decodable {}

    private func request<Body: Encodable, Response: Decodable>(
        method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws -> Response {
        let resolvedURL = try makeURL(path: path)

        var urlRequest = URLRequest(url: resolvedURL)
        urlRequest.httpMethod = method
        urlRequest.setValue("application/json", forHTTPHeaderField: "Accept")

        if authenticated {
            guard let token = try await tokenProvider.accessToken(), !token.isEmpty else {
                throw DesktopAPIClientError.missingAccessToken
            }
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body {
            urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do {
                urlRequest.httpBody = try encoder.encode(body)
            } catch {
                throw DesktopAPIClientError.encodingFailed
            }
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch {
            throw DesktopAPIClientError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw DesktopAPIClientError.invalidResponse
        }

        if !(200...299).contains(http.statusCode) {
            let envelope = try? decoder.decode(APIErrorEnvelope.self, from: data)
            throw DesktopAPIClientError.httpStatus(http.statusCode, envelope)
        }

        if Response.self == EmptyResponse.self {
            return EmptyResponse() as! Response
        }

        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw DesktopAPIClientError.decodingFailed
        }
    }

    private func makeURL(path: String) throws -> URL {
        let trimmed = path.hasPrefix("/") ? path : "/\(path)"
        guard let url = URL(string: trimmed, relativeTo: baseURL)?.absoluteURL else {
            throw DesktopAPIClientError.invalidResponse
        }
        return url
    }

    private func requestData(
        method: String,
        path: String,
        authenticated: Bool
    ) async throws -> Data {
        var urlRequest = URLRequest(url: try makeURL(path: path))
        urlRequest.httpMethod = method
        if authenticated {
            guard let token = try await tokenProvider.accessToken(), !token.isEmpty else {
                throw DesktopAPIClientError.missingAccessToken
            }
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (data, response) = try await session.data(for: urlRequest)
            guard let http = response as? HTTPURLResponse else {
                throw DesktopAPIClientError.invalidResponse
            }
            guard (200...299).contains(http.statusCode) else {
                let envelope = try? decoder.decode(APIErrorEnvelope.self, from: data)
                throw DesktopAPIClientError.httpStatus(http.statusCode, envelope)
            }
            return data
        } catch let error as DesktopAPIClientError {
            throw error
        } catch {
            throw DesktopAPIClientError.transport(error.localizedDescription)
        }
    }
}
