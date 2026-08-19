import Foundation
import Security

/// Keychain-backed credential store. Secrets are never logged.
public final class KeychainCredentialStore: CredentialStore, @unchecked Sendable {
    public struct Configuration: Sendable {
        public var service: String
        public var account: String
        public var accessGroup: String?

        public init(
            service: String = "com.markremote.device-credentials",
            account: String = "paired-device",
            accessGroup: String? = nil
        ) {
            self.service = service
            self.account = account
            self.accessGroup = accessGroup
        }
    }

    private let configuration: Configuration
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    public init(configuration: Configuration = Configuration()) {
        self.configuration = configuration
    }

    public func save(_ credentials: DeviceCredentials) throws {
        let payload = StoredPayload(
            deviceId: credentials.deviceId,
            deviceSecret: credentials.deviceSecret,
            refreshToken: credentials.refreshToken,
            expiresAt: credentials.expiresAt
        )
        let data: Data
        do {
            data = try encoder.encode(payload)
        } catch {
            throw CredentialStoreError.encodingFailed
        }

        try deleteQuietly()

        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: configuration.service,
            kSecAttrAccount as String: configuration.account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        if let accessGroup = configuration.accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw CredentialStoreError.underlying("SecItemAdd failed (\(status))")
        }
    }

    public func load() throws -> DeviceCredentials? {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: configuration.service,
            kSecAttrAccount as String: configuration.account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        if let accessGroup = configuration.accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess, let data = result as? Data else {
            throw CredentialStoreError.underlying("SecItemCopyMatching failed (\(status))")
        }

        do {
            let payload = try decoder.decode(StoredPayload.self, from: data)
            return DeviceCredentials(
                deviceId: payload.deviceId,
                deviceSecret: payload.deviceSecret,
                refreshToken: payload.refreshToken,
                expiresAt: payload.expiresAt
            )
        } catch {
            throw CredentialStoreError.decodingFailed
        }
    }

    public func delete() throws {
        try deleteQuietly()
    }

    private func deleteQuietly() throws {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: configuration.service,
            kSecAttrAccount as String: configuration.account,
        ]
        if let accessGroup = configuration.accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw CredentialStoreError.underlying("SecItemDelete failed (\(status))")
        }
    }
}

private struct StoredPayload: Codable {
    var deviceId: String
    var deviceSecret: String
    var refreshToken: String?
    var expiresAt: Double?
}
