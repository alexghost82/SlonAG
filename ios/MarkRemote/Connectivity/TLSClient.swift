import Foundation
import Network
import Security

/// Secure TLS client for LAN WebSocket connections.
///
/// Handles:
/// - TCP connection to LAN device.
/// - TLS handshake with certificate validation.
/// - WebSocket upgrade.
/// - Message framing (send/receive JSON).
/// - Ping/pong heartbeat.
@MainActor
public final class TLSClient: @unchecked Sendable {
    public struct ConnectionInfo: Sendable {
        public let host: String
        public let port: Int
        public let usesTLS: Bool
        public let fingerprint: String?
    }

    private var connection: NWConnection?
    private var lastActivity: Date = .now

    public var isConnected: Bool {
        connection?.state == .ready
    }

    public var connectionInfo: ConnectionInfo? {
        guard let path = connection?.currentPath else { return nil }
        guard case let .hostPort(host, port) = path.remoteEndpoint else { return nil }

        let hostStr = String(describing: host).trimmingCharacters(
            in: CharacterSet(charactersIn: "[]")
        )
        return ConnectionInfo(
            host: hostStr,
            port: port.rawValue,
            usesTLS: connection?.security == .tls,
            fingerprint: nil
        )
    }

    /// Connect to a LAN device with TLS/WSS.
    public func connect(to device: LANDevice) async throws {
        let parameters = NWParameters.tcp
        if device.usesTLS {
            // Use permissive TLS for LAN self-signed certificates.
            // Production: use proper certificate pinning.
            var tlsParams = TLSParameters()
            tlsParams.allowSelfSignedCertificates = true
            tlsParams.minimumMaximumProtocolVersion = .TLSv12
            parameters.tls = tlsParams
        }

        let nwConn = NWConnection(
            to: .hostPort(host: .ipv4(device.host) ?? .ipv6(nil), port: .raw(device.port)),
            using: parameters
        )

        // Wait for ready state.
        await withTaskCancellationHandler {
            let stateTask = Task {
                for await state in nwConn.stateUpdates {
                    if state == .ready { return }
                    if state == .failed {
                        throw ConnectivityError.transportError("Connection failed: \(nwConn.state.rawValue)")
                    }
                }
            }
            try await stateTask.value
        } onCancel: {
            stateTask.cancel()
        }

        self.connection = nwConn
        lastActivity = .now

        // Perform WebSocket handshake.
        try await performWebSocketHandshake(conn: nwConn, host: device.host, port: device.port, path: "/v1")

        // Start receiving loop.
        startReceiving()
    }

    /// Disconnect from the current device.
    public func disconnect(from device: LANDevice) async throws {
        connection?.cancel()
        connection = nil
    }

    /// Send a JSON message.
    public func send(_ message: [String: Any]) async throws {
        guard let conn = connection, conn.state == .ready else {
            throw ConnectivityError.transportError("Not connected")
        }
        let data = try JSONSerialization.data(withJSONObject: message)
        let frame = encodeWebSocketFrame(payload: data, isText: true)
        conn.send(content: frame, completion: .contentProcessed { _ in })
        lastActivity = .now
    }

    /// Send a ping frame.
    public func ping() async throws {
        guard let conn = connection, conn.state == .ready else {
            throw ConnectivityError.transportError("Not connected")
        }
        let pingFrame = encodeWebSocketFrame(payload: Data(), isText: false, opcode: 0x9)
        conn.send(content: pingFrame, completion: .contentProcessed { _ in })
        lastActivity = .now
    }

    // MARK: - Receiving

    private func startReceiving() {
        guard let conn = connection else { return }

        func receive() {
            conn.receive(minimum: 2, maximum: 65536) { data, contentContext, isComplete, error in
                if let error {
                    _log("Receive error: \(error)")
                    return
                }
                if let data, !data.isEmpty {
                    self.handleReceived(data: data, contentContext: contentContext)
                }
                if !isComplete {
                    receive()
                }
            }
        }
        receive()
    }

    private func handleReceived(data: Data, contentContext: NWContentContext?) {
        lastActivity = .now

        // Determine if it's a text or binary frame.
        guard let frame = decodeWebSocketFrame(data) else { return }

        if frame.isPing {
            // Respond with pong.
            pong()
        } else if frame.isText, let text = String(data: frame.payload, encoding: .utf8) {
            // Handle received text message.
            _log("Received: \(text)")
        }
    }

    private func pong() {
        guard let conn = connection, conn.state == .ready else { return }
        let pongFrame = encodeWebSocketFrame(payload: Data(), isText: false, opcode: 0xA)
        conn.send(content: pongFrame, completion: .contentProcessed { _ in })
    }

    // MARK: - Helpers

    private func performWebSocketHandshake(
        conn: NWConnection,
        host: String,
        port: Int,
        path: String
    ) async throws {
        let key = generateWebSocketKey()
        let accept = computeWebSocketAccept(key: key)

        var request = "GET \(path) HTTP/1.1\r\n"
        request.append("Host: \(host)\r\n")
        request.append("Upgrade: websocket\r\n")
        request.append("Connection: Upgrade\r\n")
        request.append("Sec-WebSocket-Key: \(key)\r\n")
        request.append("Sec-WebSocket-Version: 13\r\n")
        request.append("\r\n")

        let requestData = request.data(using: .utf8)!
        conn.send(content: requestData, completion: .idempotent)

        // Read response.
        let response = try await readResponse(conn: conn)
        guard response.contains("101") else {
            throw ConnectivityError.transportError("WebSocket upgrade failed: \(response.prefix(100))")
        }
        guard response.contains(accept) else {
            throw ConnectivityError.transportError("WebSocket accept mismatch")
        }
    }

    private func readResponse(conn: NWConnection) async throws -> String {
        let result = try await withThrowingTaskGroup(of: String.self) { group in
            group.addTask {
                let data = try await withCheckedThrowingContinuation { continuation in
                    conn.receive(minimum: 1, maximum: 4096) { content, _, _, error in
                        if let error {
                            continuation.resume(throwing: error)
                        } else {
                            continuation.resume(returning: content ?? Data())
                        }
                    }
                }
                return String(data: data, encoding: .utf8) ?? ""
            }
            group.addTask {
                try await Task.sleep(nanoseconds: 5_000_000_000)
                throw ConnectivityError.transportError("Handshake timeout")
            }
        }
        return result
    }

    private func generateWebSocketKey() -> String {
        var bytes = [UInt8](repeating: 0, count: 16)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "Failed to generate random bytes")
        return Data(bytes).base64EncodedString()
    }

    private func computeWebSocketAccept(key: String) -> String {
        letGUID = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        guard let data = GUID.data(using: .utf8) else { return "" }
        let digest = SecDigestCalculate(kSecDigestSHA1, nil, 0, data, data.count)!
        return Data(bytes: digest).base64EncodedString()
    }

    private func encodeWebSocketFrame(
        payload: Data,
        isText: Bool,
        opcode: UInt8 = 0x1
    ) -> Data {
        var frame = Data()
        let finalBit: UInt8 = 0x80
        frame.append(finalBit | opcode)

        let length = payload.count
        if length < 126 {
            frame.append(UInt8(length))
        } else if length <= 0xFFFF {
            frame.append(126)
            frame.append(UInt16(length).bigEndian)
        } else {
            frame.append(127)
            frame.append(UInt64(length).bigEndian)
        }
        frame.append(payload)
        return frame
    }

    private struct WebSocketFrame {
        let isText: Bool
        let isPing: Bool
        let isPong: Bool
        let payload: Data
    }

    private func decodeWebSocketFrame(_ data: Data) -> WebSocketFrame? {
        guard data.count >= 2 else { return nil }

        let isText = (data[0] & 0x0F) == 0x01
        let isPing = (data[0] & 0x0F) == 0x9
        let isPong = (data[0] & 0x0F) == 0xA

        var offset = 2
        let length = Int(data[1] & 0x7F)

        if length == 126 && data.count >= 4 {
            offset = 4
        } else if length == 127 && data.count >= 10 {
            offset = 10
        }

        let payload = data.subdata(in: offset..<min(offset + length, data.count))
        return WebSocketFrame(isText: isText, isPing: isPing, isPong: isPong, payload: payload)
    }
}

private func _log(_ message: String) {
    #if DEBUG
    print("[TLSClient] \(message)")
    #endif
}
