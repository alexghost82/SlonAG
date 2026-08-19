import DesignSystem
import SwiftUI

public struct SettingsFeatureView: View {
    @Bindable private var viewModel: SettingsViewModel

    public init(viewModel: SettingsViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        List {
            Section {
                MRSectionHeader(
                    "Устройство",
                    subtitle: "Идентификатор сопряжения не является секретом. Секрет устройства здесь не показывается."
                )
            }

            Section("Сопряжение") {
                if let deviceId = viewModel.pairedDeviceId {
                    LabeledContent("ID устройства") {
                        Text(deviceId)
                            .font(MRTypography.caption)
                            .foregroundStyle(MRColor.secondaryLabel)
                            .textSelection(.enabled)
                    }
                    Button("Отозвать сопряжение", role: .destructive) {
                        viewModel.requestRevoke()
                    }
                } else {
                    Text("Нет сопряжённого устройства")
                        .foregroundStyle(MRColor.secondaryLabel)
                }
            }

            Section("Сеть") {
                LabeledContent("Режим сети") {
                    Text(viewModel.networkModeDisplay)
                        .foregroundStyle(MRColor.secondaryLabel)
                }
                Text("Публичный доступ Desktop API и прослушивание 0.0.0.0 из приложения недоступны.")
                    .font(MRTypography.caption)
                    .foregroundStyle(MRColor.tertiaryLabel)
            }

            Section("Память") {
                Button("Очистить память на компьютере", role: .destructive) {
                    viewModel.requestClearMemory()
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
        .navigationTitle("Настройки")
        .confirmationDialog(
            "Отозвать сопряжение?",
            isPresented: Binding(
                get: { viewModel.revokeConfirmationPending },
                set: { if !$0 { viewModel.cancelRevoke() } }
            ),
            titleVisibility: .visible
        ) {
            Button("Отозвать", role: .destructive) {
                viewModel.confirmRevoke()
            }
            Button("Отмена", role: .cancel) {
                viewModel.cancelRevoke()
            }
        } message: {
            Text("Устройство потеряет доступ к desktop-клиенту.")
        }
        .confirmationDialog(
            "Очистить память?",
            isPresented: Binding(
                get: { viewModel.clearMemoryConfirmationPending },
                set: { if !$0 { viewModel.cancelClearMemory() } }
            ),
            titleVisibility: .visible
        ) {
            Button("Очистить", role: .destructive) {
                Task { await viewModel.confirmClearMemory() }
            }
            Button("Отмена", role: .cancel) {
                viewModel.cancelClearMemory()
            }
        } message: {
            Text("Все записи памяти на компьютере будут удалены.")
        }
        .task {
            await viewModel.load()
        }
        // Compile-time / API guarantee: no public bind toggle exists on this view model.
        .onAppear {
            assert(!viewModel.exposesPublicBindControl)
        }
    }
}
