import Foundation
import MarkRemoteNetworking
import MarkRemoteSecurity

/// Mints and caches short-lived Bearer tokens from stored pairing credentials.
///
/// Calls `POST /v1/auth/token` with the device credential. The device secret
/// never leaves the Keychain except for this exchange, and is never logged.
final class DeviceTokenProvider: AccessTokenProviding, @unchecked Sendable {
    private struct TokenResponse: Decodable {
        let accessToken: String
        let expiresAt: Double?
    }

    private let baseURL: URL
    private let credentialStore: any CredentialStore
    private let session: URLSession
    private let lock = NSLock()

    private var cachedToken: String?
    private var cachedExpiry: Double?

    init(baseURL: URL, credentialStore: any CredentialStore, session: URLSession) {
        self.baseURL = baseURL
        self.credentialStore = credentialStore
        self.session = session
    }

    func invalidate() {
        lock.lock()
        cachedToken = nil
        cachedExpiry = nil
        lock.unlock()
    }

    func accessToken() async throws -> String? {
        if let token = validCachedToken() {
            return token
        }
        guard let credentials = try credentialStore.load() else {
            return nil
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("v1/auth/token"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "device_id": credentials.deviceId,
            "device_secret": credentials.deviceSecret,
        ])

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            return nil
        }

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let decoded = try decoder.decode(TokenResponse.self, from: data)

        lock.lock()
        cachedToken = decoded.accessToken
        cachedExpiry = decoded.expiresAt
        lock.unlock()
        return decoded.accessToken
    }

    private func validCachedToken() -> String? {
        lock.lock()
        defer { lock.unlock() }
        guard let token = cachedToken else { return nil }
        if let expiry = cachedExpiry, expiry - 5 <= Date().timeIntervalSince1970 {
            return nil
        }
        return token
    }
}
