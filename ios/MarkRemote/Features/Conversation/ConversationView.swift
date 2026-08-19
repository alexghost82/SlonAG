import DesignSystem
import MarkRemoteModels
import SwiftUI

/// Streaming chat UI with message list, cancel, approval chips, and attachment/camera stubs.
public struct ConversationView: View {
    @Bindable private var viewModel: ConversationViewModel

    public init(viewModel: ConversationViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        VStack(spacing: 0) {
            if viewModel.messages.isEmpty {
                MREmptyState(
                    title: ConversationStrings.emptyTitle,
                    message: ConversationStrings.emptyMessage,
                    systemImage: "bubble.left.and.bubble.right"
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                messageList
            }

            if !viewModel.pendingApprovals.isEmpty {
                pendingApprovalsBar
            }

            if let error = viewModel.lastErrorMessage {
                Text(error)
                    .font(MRTypography.footnote)
                    .foregroundStyle(MRColor.danger)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, MRSpacing.md)
                    .padding(.vertical, MRSpacing.xxs)
                    .accessibilityLabel(error)
            }

            composer
        }
        .background(MRColor.groupedBackground)
        .navigationTitle(ConversationStrings.title)
        .toolbar {
            if viewModel.canCancel {
                ToolbarItem(placement: .cancellationAction) {
                    Button(ConversationStrings.cancelGeneration) {
                        viewModel.cancelGeneration()
                    }
                    .accessibilityLabel(ConversationStrings.cancelGeneration)
                }
            }
        }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: MRSpacing.sm) {
                    ForEach(viewModel.messages) { message in
                        messageBubble(message)
                            .id(message.id)
                    }
                }
                .padding(MRSpacing.md)
            }
            .onChange(of: viewModel.messages.count) { _, _ in
                if let last = viewModel.messages.last {
                    withAnimation {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func messageBubble(_ message: ConversationMessage) -> some View {
        let isUser = message.role == .user
        VStack(alignment: isUser ? .trailing : .leading, spacing: MRSpacing.xxxs) {
            Text(isUser ? ConversationStrings.roleUser : ConversationStrings.roleAssistant)
                .font(MRTypography.caption2)
                .foregroundStyle(MRColor.secondaryLabel)

            Text(message.text.isEmpty && message.isStreaming ? ConversationStrings.streaming : message.text)
                .font(MRTypography.body)
                .foregroundStyle(MRColor.label)
                .padding(.horizontal, MRSpacing.sm)
                .padding(.vertical, MRSpacing.xs)
                .background(
                    isUser ? MRColor.accent.opacity(0.15) : MRColor.secondaryBackground,
                    in: RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous)
                )
                .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
                .accessibilityLabel(
                    "\(isUser ? ConversationStrings.roleUser : ConversationStrings.roleAssistant): \(message.text)"
                )
        }
    }

    private var pendingApprovalsBar: some View {
        VStack(alignment: .leading, spacing: MRSpacing.xxs) {
            Text(ConversationStrings.pendingApprovals)
                .font(MRTypography.caption.weight(.semibold))
                .foregroundStyle(MRColor.secondaryLabel)
                .padding(.horizontal, MRSpacing.md)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: MRSpacing.xs) {
                    ForEach(viewModel.pendingApprovals) { chip in
                        Text(chip.toolName.isEmpty ? ConversationStrings.approvalChipFallback : chip.toolName)
                            .font(MRTypography.caption)
                            .padding(.horizontal, MRSpacing.sm)
                            .padding(.vertical, MRSpacing.xxs)
                            .background(MRColor.warning.opacity(0.2), in: Capsule())
                            .accessibilityLabel(chip.toolName)
                            .onTapGesture {
                                viewModel.dismissApprovalChip(id: chip.id)
                            }
                    }
                }
                .padding(.horizontal, MRSpacing.md)
            }
        }
        .padding(.vertical, MRSpacing.xs)
    }

    private var composer: some View {
        VStack(spacing: MRSpacing.xs) {
            HStack(spacing: MRSpacing.xs) {
                Button {
                    Task { await viewModel.attachFileStub() }
                } label: {
                    Image(systemName: "paperclip")
                        .font(MRTypography.headline)
                        .foregroundStyle(MRColor.accent)
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(ConversationStrings.attach)
                .accessibilityHint(ConversationStrings.attachStubHint)

                Button {
                    Task { await viewModel.openCameraStub() }
                } label: {
                    Image(systemName: "camera")
                        .font(MRTypography.headline)
                        .foregroundStyle(MRColor.accent)
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(ConversationStrings.camera)
                .accessibilityHint(ConversationStrings.cameraStubHint)

                TextField(ConversationStrings.inputPlaceholder, text: $viewModel.draft, axis: .vertical)
                    .font(MRTypography.body)
                    .lineLimit(1...5)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, MRSpacing.sm)
                    .padding(.vertical, MRSpacing.xs)
                    .background(MRColor.secondaryBackground, in: RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous))

                if viewModel.canCancel {
                    Button(ConversationStrings.cancel) {
                        viewModel.cancelGeneration()
                    }
                    .font(MRTypography.subheadline.weight(.semibold))
                    .foregroundStyle(MRColor.danger)
                    .accessibilityLabel(ConversationStrings.cancelGeneration)
                } else {
                    Button(ConversationStrings.send) {
                        viewModel.sendDraft()
                    }
                    .font(MRTypography.subheadline.weight(.semibold))
                    .foregroundStyle(viewModel.canSend ? MRColor.accent : MRColor.tertiaryLabel)
                    .disabled(!viewModel.canSend)
                    .accessibilityLabel(ConversationStrings.send)
                }
            }
            .padding(.horizontal, MRSpacing.md)
            .padding(.vertical, MRSpacing.sm)

            Text(ConversationStrings.noProviderKeysOnDevice)
                .font(MRTypography.caption2)
                .foregroundStyle(MRColor.tertiaryLabel)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, MRSpacing.md)
                .padding(.bottom, MRSpacing.xs)
        }
        .background(MRColor.background)
    }
}

#Preview("Conversation") {
    NavigationStack {
        ConversationView(
            viewModel: ConversationViewModel(
                chatClient: FakeChatStreamingClient(events: [
                    ChatStreamEvent(event: "delta", conversationId: "c1", delta: "Привет!"),
                    ChatStreamEvent(event: "done", conversationId: "c1"),
                ])
            )
        )
    }
}
