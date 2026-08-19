import Foundation
import MarkRemoteModels

/// Role of a chat bubble in the conversation list.
public enum ConversationMessageRole: String, Sendable, Equatable, CaseIterable {
    case user
    case assistant
    case system
}

/// One message shown in the conversation history.
public struct ConversationMessage: Identifiable, Sendable, Equatable {
    public var id: String
    public var role: ConversationMessageRole
    public var text: String
    public var isStreaming: Bool
    public var createdAt: Date

    public init(
        id: String = UUID().uuidString,
        role: ConversationMessageRole,
        text: String,
        isStreaming: Bool = false,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.role = role
        self.text = text
        self.isStreaming = isStreaming
        self.createdAt = createdAt
    }
}

/// Lightweight chip for a pending tool approval (data only; decision UI lives elsewhere).
public struct PendingApprovalChip: Identifiable, Sendable, Equatable {
    public var id: String
    public var toolName: String
    public var risk: String

    public init(id: String, toolName: String, risk: String = "") {
        self.id = id
        self.toolName = toolName
        self.risk = risk
    }

    public init(from info: ApprovalInfo) {
        self.id = info.id
        self.toolName = info.toolName
        self.risk = info.risk
    }
}

/// Attachment / camera affordances — stubs until an upload client is injected.
public enum ConversationComposerAction: String, Sendable, Equatable {
    case attachFile
    case openCamera
}
