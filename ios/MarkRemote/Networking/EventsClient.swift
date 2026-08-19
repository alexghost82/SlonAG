import Foundation
import MarkRemoteModels

/// Event payload from `/v1/events`.
public struct DesktopEvent: Codable, Sendable, Equatable {
    public var type: String?
    public var payload: [String: String]

    public init(type: String? = nil, payload: [String: String] = [:]) {
        self.type = type
        self.payload = payload
    }
}

public enum EventsClientError: Error, Sendable, Equatable {
    case notConnected
    case closed
    case decodingFailed
    case transport(String)
}

/// WebSocket-style events client for `/v1/events`.
public protocol EventsClient: Sendable {
    func connect() async throws
    func disconnect() async
    func receive() async throws -> DesktopEvent
}

/// Production client backed by `URLSessionWebSocketTask`.
public actor URLSessionEventsClient: EventsClient {
    private let baseURL: URL
    private let session: URLSession
    private let tokenProvider: any AccessTokenProviding
    private let decoder: JSONDecoder
    private var task: URLSessionWebSocketTask?

    public init(
        baseURL: URL,
        session: URLSession = .shared,
        tokenProvider: any AccessTokenProviding,
        decoder: JSONDecoder = DesktopAPIJSON.decoder
    ) {
        self.baseURL = baseURL
        self.session = session
        self.tokenProvider = tokenProvider
        self.decoder = decoder
    }

    public func connect() async throws {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("v1/events"),
            resolvingAgainstBaseURL: true
        )
        if components?.scheme == "http" {
            components?.scheme = "ws"
        } else if components?.scheme == "https" {
            components?.scheme = "wss"
        }
        guard let url = components?.url else {
            throw EventsClientError.transport("Invalid events URL")
        }

        var request = URLRequest(url: url)
        if let token = try await tokenProvider.accessToken(), !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let webSocket = session.webSocketTask(with: request)
        task = webSocket
        webSocket.resume()
    }

    public func disconnect() async {
        let current = task
        task = nil
        current?.cancel(with: .goingAway, reason: nil)
    }

    public func receive() async throws -> DesktopEvent {
        guard let current = task else {
            throw EventsClientError.notConnected
        }

        do {
            let message = try await current.receive()
            switch message {
            case .string(let text):
                guard let data = text.data(using: .utf8) else {
                    throw EventsClientError.decodingFailed
                }
                return try decodeEvent(from: data)
            case .data(let data):
                return try decodeEvent(from: data)
            @unknown default:
                throw EventsClientError.decodingFailed
            }
        } catch let error as EventsClientError {
            throw error
        } catch {
            throw EventsClientError.transport(error.localizedDescription)
        }
    }

    private func decodeEvent(from data: Data) throws -> DesktopEvent {
        if let event = try? decoder.decode(DesktopEvent.self, from: data) {
            return event
        }
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw EventsClientError.decodingFailed
        }
        let type = object["type"] as? String
        var payload: [String: String] = [:]
        for (key, value) in object where key != "type" {
            payload[key] = String(describing: value)
        }
        return DesktopEvent(type: type, payload: payload)
    }
}

/// In-memory fake for unit tests.
public actor FakeEventsClient: EventsClient {
    private var queue: [DesktopEvent]
    private var connected = false

    public init(events: [DesktopEvent] = []) {
        self.queue = events
    }

    public func enqueue(_ event: DesktopEvent) {
        queue.append(event)
    }

    public func connect() async throws {
        connected = true
    }

    public func disconnect() async {
        connected = false
    }

    public func receive() async throws -> DesktopEvent {
        guard connected else {
            throw EventsClientError.notConnected
        }
        guard !queue.isEmpty else {
            throw EventsClientError.closed
        }
        return queue.removeFirst()
    }
}
