import Foundation
import MarkRemoteModels
import Observation

/// Drives streaming chat: append deltas, cancel in-flight generation, pending approval chips.
@MainActor
@Observable
public final class ConversationViewModel {
    public private(set) var messages: [ConversationMessage] = []
    public private(set) var pendingApprovals: [PendingApprovalChip] = []
    public private(set) var conversationId: String?
    public private(set) var isStreaming = false
    public private(set) var lastErrorMessage: String?
    public private(set) var lastComposerAction: ConversationComposerAction?
    public var draft: String = ""

    /// Product invariant exposed for tests / settings copy.
    public let storesProviderAPIKeysOnDevice = false

    private let chatClient: any ChatStreamingServing
    private let attachmentHandler: any ConversationAttachmentHandling
    private let idempotencyKeyFactory: @Sendable () -> String
    private var streamTask: Task<Void, Never>?
    private var streamingAssistantMessageId: String?

    public init(
        chatClient: any ChatStreamingServing,
        attachmentHandler: any ConversationAttachmentHandling = StubConversationAttachmentHandler(),
        idempotencyKeyFactory: @escaping @Sendable () -> String = { UUID().uuidString },
        conversationId: String? = nil,
        initialMessages: [ConversationMessage] = []
    ) {
        self.chatClient = chatClient
        self.attachmentHandler = attachmentHandler
        self.idempotencyKeyFactory = idempotencyKeyFactory
        self.conversationId = conversationId
        self.messages = initialMessages
    }

    public var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isStreaming
    }

    public var canCancel: Bool {
        isStreaming
    }

    public func sendDraft() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isStreaming else { return }
        draft = ""
        send(text: text)
    }

    public func send(text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isStreaming else { return }

        lastErrorMessage = nil
        messages.append(ConversationMessage(role: .user, text: trimmed))

        let assistantId = UUID().uuidString
        streamingAssistantMessageId = assistantId
        messages.append(
            ConversationMessage(id: assistantId, role: .assistant, text: "", isStreaming: true)
        )
        isStreaming = true

        let key = idempotencyKeyFactory()
        let existingConversationId = conversationId
        let client = chatClient

        streamTask?.cancel()
        streamTask = Task { [weak self] in
            guard let self else { return }
            let stream = client.streamChat(
                message: trimmed,
                conversationId: existingConversationId,
                idempotencyKey: key
            )
            do {
                for try await event in stream {
                    if Task.isCancelled { break }
                    self.apply(event: event, assistantMessageId: assistantId)
                }
                self.finishStreaming(assistantMessageId: assistantId, cancelled: Task.isCancelled)
            } catch is CancellationError {
                self.finishStreaming(assistantMessageId: assistantId, cancelled: true)
            } catch {
                self.failStreaming(
                    assistantMessageId: assistantId,
                    message: ConversationStrings.errorGeneric
                )
            }
        }
    }

    public func cancelGeneration() {
        guard isStreaming else { return }
        streamTask?.cancel()
        streamTask = nil
        if let id = streamingAssistantMessageId,
           let index = messages.firstIndex(where: { $0.id == id }) {
            messages[index].isStreaming = false
            if messages[index].text.isEmpty {
                messages[index].text = "…"
            }
        }
        streamingAssistantMessageId = nil
        isStreaming = false
    }

    public func attachFileStub() async {
        lastComposerAction = .attachFile
        await attachmentHandler.handleAttachFile()
    }

    public func openCameraStub() async {
        lastComposerAction = .openCamera
        await attachmentHandler.handleOpenCamera()
    }

    public func dismissApprovalChip(id: String) {
        pendingApprovals.removeAll { $0.id == id }
    }

    public func upsertPendingApproval(_ chip: PendingApprovalChip) {
        if let index = pendingApprovals.firstIndex(where: { $0.id == chip.id }) {
            pendingApprovals[index] = chip
        } else {
            pendingApprovals.append(chip)
        }
    }

    private func apply(event: ChatStreamEvent, assistantMessageId: String) {
        if let cid = event.conversationId, !cid.isEmpty {
            conversationId = cid
        }

        switch event.event {
        case "delta":
            guard let delta = event.delta, !delta.isEmpty else { return }
            appendDelta(delta, to: assistantMessageId)
        case "approval_required":
            let approvalId = event.approvalId ?? UUID().uuidString
            upsertPendingApproval(
                PendingApprovalChip(
                    id: approvalId,
                    toolName: ConversationStrings.approvalChipFallback,
                    risk: ""
                )
            )
        case "done":
            break
        case "error":
            let message = event.error?.message ?? ConversationStrings.errorGeneric
            lastErrorMessage = message
        default:
            if let delta = event.delta, !delta.isEmpty {
                appendDelta(delta, to: assistantMessageId)
            }
            if event.approvalRequired || event.approvalId != nil {
                let approvalId = event.approvalId ?? UUID().uuidString
                upsertPendingApproval(
                    PendingApprovalChip(
                        id: approvalId,
                        toolName: ConversationStrings.approvalChipFallback,
                        risk: ""
                    )
                )
            }
        }
    }

    private func appendDelta(_ delta: String, to assistantMessageId: String) {
        guard let index = messages.firstIndex(where: { $0.id == assistantMessageId }) else { return }
        messages[index].text += delta
        messages[index].isStreaming = true
    }

    private func finishStreaming(assistantMessageId: String, cancelled: Bool) {
        if let index = messages.firstIndex(where: { $0.id == assistantMessageId }) {
            messages[index].isStreaming = false
            if cancelled, messages[index].text.isEmpty {
                messages[index].text = "…"
            }
        }
        if streamingAssistantMessageId == assistantMessageId {
            streamingAssistantMessageId = nil
        }
        isStreaming = false
        streamTask = nil
    }

    private func failStreaming(assistantMessageId: String, message: String) {
        lastErrorMessage = message
        if let index = messages.firstIndex(where: { $0.id == assistantMessageId }) {
            messages[index].isStreaming = false
            if messages[index].text.isEmpty {
                messages.remove(at: index)
            }
        }
        streamingAssistantMessageId = nil
        isStreaming = false
        streamTask = nil
    }
}
