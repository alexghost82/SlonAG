import DesignSystem
import SwiftUI

/// Main remote panel: online badge, provider/model, network, runtime, mic, controls.
public struct DashboardView: View {
    @Bindable private var viewModel: DashboardViewModel

    public init(viewModel: DashboardViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: MRSpacing.lg) {
                header
                statusRows
                controls
                if let errorMessage = viewModel.errorMessage {
                    Text(errorMessage)
                        .font(MRTypography.footnote)
                        .foregroundStyle(MRColor.danger)
                        .accessibilityLabel(errorMessage)
                }
            }
            .padding(MRSpacing.md)
        }
        .background(MRColor.groupedBackground)
        .navigationTitle("Панель")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                MRStatusBadge(viewModel.connectionStatus)
            }
            ToolbarItem(placement: .automatic) {
                Button {
                    Task { await viewModel.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .accessibilityLabel("Обновить")
                .disabled(viewModel.isBusy)
            }
        }
        .task {
            await viewModel.refresh()
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: MRSpacing.sm) {
            MRSectionHeader(
                "Рабочий стол",
                subtitle: "Состояние Mark Remote без ключей провайдеров."
            )
            Spacer(minLength: 0)
            MRStatusBadge(viewModel.connectionStatus)
        }
    }

    private var statusRows: some View {
        VStack(alignment: .leading, spacing: MRSpacing.sm) {
            statusRow(title: "Провайдер", value: viewModel.providerText)
            statusRow(title: "Модель", value: viewModel.modelText)
            statusRow(title: "Режим сети", value: viewModel.networkModeText)
            statusRow(title: "Runtime", value: viewModel.runtimeText)
            statusRow(
                title: "Микрофон",
                value: viewModel.micIndicatorText,
                systemImage: viewModel.snapshot.micActive ? "mic.fill" : "mic.slash"
            )
        }
    }

    private func statusRow(title: String, value: String, systemImage: String? = nil) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: MRSpacing.sm) {
            Text(title)
                .font(MRTypography.subheadline)
                .foregroundStyle(MRColor.secondaryLabel)
                .frame(width: 110, alignment: .leading)
            if let systemImage {
                Image(systemName: systemImage)
                    .foregroundStyle(MRColor.secondaryLabel)
                    .accessibilityHidden(true)
            }
            Text(value)
                .font(MRTypography.body)
                .foregroundStyle(MRColor.label)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(MRSpacing.sm)
        .background(MRColor.secondaryBackground, in: RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title): \(value)")
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: MRSpacing.sm) {
            MRSectionHeader("Ассистент", subtitle: "Запуск, пауза и остановка сессии.")

            HStack(spacing: MRSpacing.sm) {
                MRPrimaryButton("Старт", systemImage: "play.fill") {
                    Task { await viewModel.start() }
                }
                .disabled(viewModel.isBusy)

                MRSecondaryButton("Пауза", systemImage: "pause.fill") {
                    Task { await viewModel.pause() }
                }
                .disabled(viewModel.isBusy)

                MRSecondaryButton("Стоп", systemImage: "stop.fill") {
                    Task { await viewModel.stop() }
                }
                .disabled(viewModel.isBusy)
            }
        }
    }
}

#Preview("Панель") {
    NavigationStack {
        DashboardView(
            viewModel: DashboardViewModel(
                controller: PreviewDashboardController(),
                initial: DashboardSnapshot(
                    online: true,
                    paired: true,
                    providerId: "local",
                    modelId: "llama",
                    networkMode: "loopback",
                    runtimeStatus: "ожидание",
                    micActive: false
                )
            )
        )
    }
}

#if DEBUG
private struct PreviewDashboardController: DashboardControlling {
    func refreshStatus() async throws -> DashboardSnapshot {
        DashboardSnapshot(
            online: true,
            paired: true,
            providerId: "local",
            modelId: "llama",
            networkMode: "loopback",
            runtimeStatus: "ожидание",
            micActive: false
        )
    }

    func perform(_ action: AssistantControlAction) async throws {}
}
#endif
