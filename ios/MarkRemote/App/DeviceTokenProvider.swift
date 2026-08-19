import Foundation
import MarkRemoteNetworking
import MarkRemoteSecurity

/// Exchanges the paired-device secret for a short-lived access token.
/// Secret material remains in Keychain and is never logged.
public final class DeviceTokenProvider: AccessTokenProviding, @unchecked Sendable {
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

    public init(
        baseURL: URL,
        credentialStore: any CredentialStore,
        session: URLSession
    ) {
        self.baseURL = baseURL
        self.credentialStore = credentialStore
        self.session = session
    }

    public func invalidate() {
        lock.withLock {
            cachedToken = nil
            cachedExpiry = nil
        }
    }

    public func accessToken() async throws -> String? {
        if let token = validCachedToken() {
            return token
        }
        guard let credentials = try credentialStore.load() else {
            return nil
        }

        var request = URLRequest(url: baseURL.appending(path: "v1/auth/token"))
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
        lock.withLock {
            cachedToken = decoded.accessToken
            cachedExpiry = decoded.expiresAt
        }
        return decoded.accessToken
    }

    private func validCachedToken() -> String? {
        lock.withLock {
            guard let token = cachedToken else { return nil }
            if let expiry = cachedExpiry, expiry - 5 <= Date().timeIntervalSince1970 {
                cachedToken = nil
                cachedExpiry = nil
                return nil
            }
            return token
        }
    }
}
