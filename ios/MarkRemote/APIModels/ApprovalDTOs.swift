import Foundation

public struct ApprovalInfo: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var toolName: String
    public var risk: String
    public var status: String
    public var source: String?
    public var intent: String?

    public init(
        id: String,
        toolName: String,
        risk: String,
        status: String,
        source: String? = nil,
        intent: String? = nil
    ) {
        self.id = id
        self.toolName = toolName
        self.risk = risk
        self.status = status
        self.source = source
        self.intent = intent
    }
}

/// GET `/v1/approvals`
public struct ApprovalListResponse: Codable, Sendable, Equatable {
    public var approvals: [ApprovalInfo]

    public init(approvals: [ApprovalInfo]) {
        self.approvals = approvals
    }
}

/// POST `/v1/approvals/{id}/decision`
public struct ApprovalDecisionRequest: Codable, Sendable, Equatable {
    public var decision: String
    public var idempotencyKey: String

    public init(decision: String, idempotencyKey: String) {
        self.decision = decision
        self.idempotencyKey = idempotencyKey
    }
}
