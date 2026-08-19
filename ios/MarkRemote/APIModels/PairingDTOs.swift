import Foundation

/// POST `/v1/pairing/start`
public struct PairingStartRequest: Codable, Sendable, Equatable {
    public var idempotencyKey: String

    public init(idempotencyKey: String) {
        self.idempotencyKey = idempotencyKey
    }
}

public struct PairingStartResponse: Codable, Sendable, Equatable {
    public var code: String
    public var expiresAt: Double
    public var qrPayload: String
    public var tlsCertificateSha256: String?

    public init(
        code: String,
        expiresAt: Double,
        qrPayload: String,
        tlsCertificateSha256: String? = nil
    ) {
        self.code = code
        self.expiresAt = expiresAt
        self.qrPayload = qrPayload
        self.tlsCertificateSha256 = tlsCertificateSha256
    }
}

public struct PairingRevokeRequest: Codable, Sendable, Equatable {
    public var idempotencyKey: String

    public init(idempotencyKey: String) {
        self.idempotencyKey = idempotencyKey
    }
}

public struct PairingRevokeResponse: Codable, Sendable, Equatable {
    public var revoked: Bool

    public init(revoked: Bool) {
        self.revoked = revoked
    }
}

/// POST `/v1/pairing/complete`
public struct PairingCompleteRequest: Codable, Sendable, Equatable {
    public var code: String
    public var deviceName: String
    public var idempotencyKey: String

    public init(code: String, deviceName: String, idempotencyKey: String) {
        self.code = code
        self.deviceName = deviceName
        self.idempotencyKey = idempotencyKey
    }
}

/// Per-device credential issued once. Never includes AI provider API keys.
public struct PairingCompleteResponse: Codable, Sendable, Equatable {
    public var deviceId: String
    public var deviceSecret: String
    public var expiresAt: Double?

    public init(deviceId: String, deviceSecret: String, expiresAt: Double? = nil) {
        self.deviceId = deviceId
        self.deviceSecret = deviceSecret
        self.expiresAt = expiresAt
    }
}
