import Foundation

/// Remote transport adapter for out-of-LAN connectivity.
///
/// Connects to a remote WebSocket relay server. Only control-plane
/// messages are relayed — media flows through separate channels.
///
/// Security rules:
/// - Always uses WSS (WebSocket Secure) — no plaintext.
/// - No raw media through Firebase or any relay.
/// - No UPnP, no silent public exposure.
@MainActor
public final class RemoteAdapter: @unchecked Sendable {
    private var urlSession: URLSession?
    private var isConnected = false
    private let remoteURL: URL

    public init(url: URL = URL(string: "wss://relay.mark.local/v1/connectivity/ws")!) {
        self.remoteURL = url
        self.urlSession = URLSession(configuration: .ephemeral)
    }

    /// Check if the remote URL uses secure transport.
    public static func validateRemoteURL(_ url: URL) -> Bool {
        guard let scheme = url.scheme else { return false }
        // WSS is mandatory — no plaintext HTTP or WS.
        return scheme == "wss" || scheme == "https"
    }

    public func connect() async throws {
        // Validate secure transport.
        guard RemoteAdapter.validateRemoteURL(remoteURL) else {
            throw ConnectivityError.transportError(
                "Remote transport must use WSS or HTTPS, not \(remoteURL.scheme ?? "unknown")"
            )
        }

        // In a real implementation:
        // 1. Establish WebSocket connection using URLWebSocketTask or
        //    a third-party WebSocket library.
        // 2. Send auth handshake.
        // 3. Start message receive loop.
        isConnected = true
    }

    public func disconnect() async {
        urlSession?.invalidateAndCancel()
        urlSession = nil
        isConnected = false
    }

    public func send(_ message: [String: Any]) async throws {
        guard isConnected else {
            throw ConnectivityError.transportError("Remote adapter not connected")
        }
        // Placeholder: send via WebSocket.
    }

    public var isConnected: Bool {
        isConnected
    }
}
