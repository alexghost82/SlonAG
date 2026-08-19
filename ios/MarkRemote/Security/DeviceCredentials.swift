import Foundation

/// Opaque per-device pairing credential. Never log `deviceSecret` or refresh material.
public struct DeviceCredentials: Sendable, Equatable {
    public var deviceId: String
    public var deviceSecret: String
    public var refreshToken: String?
    public var expiresAt: Double?

    public init(
        deviceId: String,
        deviceSecret: String,
        refreshToken: String? = nil,
        expiresAt: Double? = nil
    ) {
        self.deviceId = deviceId
        self.deviceSecret = deviceSecret
        self.refreshToken = refreshToken
        self.expiresAt = expiresAt
    }

    public var debugDescription: String {
        "DeviceCredentials(deviceId: \(deviceId), deviceSecret: ***, refreshToken: \(refreshToken == nil ? "nil" : "***"), expiresAt: \(String(describing: expiresAt)))"
    }
}

extension DeviceCredentials: CustomStringConvertible, CustomDebugStringConvertible {
    public var description: String { debugDescription }
}
