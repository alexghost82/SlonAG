import Foundation

/// Common API error envelope: structured code + human message, no secrets.
public struct APIErrorEnvelope: Codable, Sendable, Equatable {
    public var code: String
    public var message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }
}
