import Foundation

/// POST `/v1/chat` — mutating; requires `idempotencyKey`.
public struct ChatRequest: Codable, Sendable, Equatable {
    public var message: String
    public var idempotencyKey: String
    public var conversationId: String?

    public init(message: String, idempotencyKey: String, conversationId: String? = nil) {
        self.message = message
        self.idempotencyKey = idempotencyKey
        self.conversationId = conversationId
    }
}

/// One streamed chat event (delta / done / approval_required / error).
public struct ChatStreamEvent: Codable, Sendable, Equatable {
    public var event: String
    public var conversationId: String?
    public var delta: String?
    public var approvalId: String?
    public var approvalRequired: Bool
    public var error: APIErrorEnvelope?

    public init(
        event: String,
        conversationId: String? = nil,
        delta: String? = nil,
        approvalId: String? = nil,
        approvalRequired: Bool = false,
        error: APIErrorEnvelope? = nil
    ) {
        self.event = event
        self.conversationId = conversationId
        self.delta = delta
        self.approvalId = approvalId
        self.approvalRequired = approvalRequired
        self.error = error
    }
}
