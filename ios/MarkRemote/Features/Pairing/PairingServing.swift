import Foundation
import MarkRemoteModels

/// Session returned by pairing start: one-time code + QR payload (text, not an image).
public struct PairingSession: Equatable, Sendable {
    public var code: String
    public var expiresAt: Double
    public var qrPayload: String

    public init(code: String, expiresAt: Double, qrPayload: String) {
        self.code = code
        self.expiresAt = expiresAt
        self.qrPayload = qrPayload
    }

    public init(_ response: PairingStartResponse) {
        self.code = response.code
        self.expiresAt = response.expiresAt
        self.qrPayload = response.qrPayload
    }
}

/// Local record of a paired desktop. Never stores AI provider API keys.
public struct PairedDeviceInfo: Identifiable, Equatable, Sendable {
    public var id: String { deviceId }
    public var deviceId: String
    public var deviceName: String

    public init(deviceId: String, deviceName: String) {
        self.deviceId = deviceId
        self.deviceName = deviceName
    }
}

/// Injectable pairing client. Production wraps `DesktopAPIClient` + credential store.
public protocol PairingServing: Sendable {
    func startPairing(idempotencyKey: String) async throws -> PairingSession
    func completePairing(code: String, deviceName: String, idempotencyKey: String) async throws -> PairedDeviceInfo
    func unpair(deviceId: String) async throws
    func listPairedDevices() async -> [PairedDeviceInfo]
}
