import Foundation

/// Supplies a short-lived Bearer access token for Desktop Control API calls.
public protocol AccessTokenProviding: Sendable {
    func accessToken() async throws -> String?
}

/// Static token provider for tests and simple wiring.
public struct StaticAccessTokenProvider: AccessTokenProviding, Sendable {
    private let token: String?

    public init(token: String?) {
        self.token = token
    }

    public func accessToken() async throws -> String? {
        token
    }
}
