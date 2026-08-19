import Foundation

/// Non-secret paired device identity for Settings display / revoke.
public protocol SettingsDeviceStoring: Sendable {
    func loadDeviceId() throws -> String?
    /// Revokes local pairing material. Must not expose or persist AI API keys.
    func revokePairing() throws
}

/// Injectable status source for network mode display only.
public protocol SettingsStatusServing: Sendable {
    func fetchNetworkMode() async throws -> String?
}

/// Optional memory clear hook used from Settings.
public protocol SettingsMemoryClearing: Sendable {
    func clearAllMemory() async throws
}
