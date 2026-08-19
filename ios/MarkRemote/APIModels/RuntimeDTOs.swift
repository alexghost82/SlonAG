import Foundation

public struct RuntimeControlRequest: Codable, Sendable, Equatable {
    public var action: String
    public var idempotencyKey: String

    public init(action: String, idempotencyKey: String) {
        self.action = action
        self.idempotencyKey = idempotencyKey
    }
}

public struct RuntimeControlResponse: Codable, Sendable, Equatable {
    public var accepted: Bool
    public var state: String

    public init(accepted: Bool, state: String) {
        self.accepted = accepted
        self.state = state
    }
}
