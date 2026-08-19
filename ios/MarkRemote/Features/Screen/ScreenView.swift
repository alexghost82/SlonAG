import DesignSystem
import SwiftUI

public struct ScreenView: View {
    @Bindable private var viewModel: ScreenViewModel

    public init(viewModel: ScreenViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        List {
            Section {
                MRSectionHeader(
                    "Экран",
                    subtitle: "Снимок по запросу или живой MJPEG-поток /v1/screen/stream (LAN). Нажатие требует подтверждения."
                )
            }

            Section {
                MRPrimaryButton("Сделать снимок", systemImage: "camera.viewfinder") {
                    Task { await viewModel.requestCapture() }
                }
                .disabled(viewModel.isCapturing)
                .listRowBackground(Color.clear)
            }

            if let placeholder = viewModel.placeholder {
                Section("Последний снимок") {
                    RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous)
                        .fill(MRColor.secondaryBackground)
                        .frame(height: 180)
                        .overlay {
                            VStack(spacing: MRSpacing.xs) {
                                Image(systemName: "rectangle.dashed")
                                    .font(.system(size: 36))
                                    .foregroundStyle(MRColor.tertiaryLabel)
                                Text(placeholder.summaryRU)
                                    .font(MRTypography.caption)
                                    .foregroundStyle(MRColor.secondaryLabel)
                                    .multilineTextAlignment(.center)
                            }
                            .padding(MRSpacing.md)
                        }
                        .accessibilityLabel("Заглушка снимка экрана")
                        .onTapGesture {
                            viewModel.proposeTap(normalizedX: 0.5, normalizedY: 0.5)
                        }

                    if viewModel.pendingTapNormalized != nil {
                        Text("Подтвердите взаимодействие с точкой на экране.")
                            .font(MRTypography.subheadline)
                            .foregroundStyle(MRColor.secondaryLabel)
                        HStack {
                            MRSecondaryButton("Отмена") {
                                viewModel.cancelPendingInteraction()
                            }
                            MRPrimaryButton("Подтвердить") {
                                _ = viewModel.confirmPendingInteraction()
                            }
                        }
                        .listRowBackground(Color.clear)
                    }

                    if viewModel.interactionConfirmationRequired {
                        Text("Для нажатий требуется подтверждение.")
                            .font(MRTypography.caption)
                            .foregroundStyle(MRColor.tertiaryLabel)
                    }
                }
            }

            if let errorMessage = viewModel.errorMessage {
                Section {
                    Text(errorMessage)
                        .font(MRTypography.subheadline)
                        .foregroundStyle(MRColor.warning)
                }
            }
        }
        .navigationTitle("Экран")
        .overlay {
            if viewModel.isCapturing {
                ProgressView("Съёмка…")
            }
        }
    }
}
