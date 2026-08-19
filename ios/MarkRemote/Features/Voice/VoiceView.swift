import DesignSystem
import SwiftUI

/// Push-to-talk control surface with interrupt affordance.
public struct VoiceView: View {
    @Bindable private var controller: VoiceSessionController
    @State private var isPressing = false

    public init(controller: VoiceSessionController) {
        self.controller = controller
    }

    public var body: some View {
        VStack(spacing: MRSpacing.lg) {
            Text(controller.statusText)
                .font(MRTypography.title)
                .foregroundStyle(MRColor.label)
                .multilineTextAlignment(.center)
                .accessibilityLabel(controller.statusText)

            if let transcript = controller.lastTranscript, !transcript.isEmpty {
                Text(transcript)
                    .font(MRTypography.body)
                    .foregroundStyle(MRColor.secondaryLabel)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, MRSpacing.md)
            }

            if let error = controller.lastErrorMessage {
                Text(error)
                    .font(MRTypography.footnote)
                    .foregroundStyle(MRColor.danger)
                    .accessibilityLabel(error)
            }

            pttButton

            if controller.state == .speaking || controller.isSpeaking {
                MRSecondaryButton(VoiceStrings.interrupt, systemImage: "stop.fill") {
                    Task { await controller.interruptTTS() }
                }
                .padding(.horizontal, MRSpacing.xl)
            }

            Text(VoiceStrings.noProviderKeysOnDevice)
                .font(MRTypography.caption2)
                .foregroundStyle(MRColor.tertiaryLabel)
                .multilineTextAlignment(.center)
                .padding(.horizontal, MRSpacing.md)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(MRColor.groupedBackground)
        .navigationTitle(VoiceStrings.title)
    }

    private var pttButton: some View {
        Image(systemName: controller.state == .recording ? "mic.fill" : "mic")
            .font(.system(size: 36, weight: .semibold))
            .foregroundStyle(Color.white)
            .frame(width: 88, height: 88)
            .background(
                controller.state == .recording ? MRColor.danger : MRColor.accent,
                in: Circle()
            )
            .accessibilityLabel(VoiceStrings.holdToTalk)
            .accessibilityHint(VoiceStrings.releaseToSend)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !isPressing else { return }
                        isPressing = true
                        Task { await controller.press() }
                    }
                    .onEnded { _ in
                        isPressing = false
                        Task { await controller.release() }
                    }
            )
    }
}

#Preview("Voice") {
    NavigationStack {
        VoiceView(controller: VoiceSessionController())
    }
}
