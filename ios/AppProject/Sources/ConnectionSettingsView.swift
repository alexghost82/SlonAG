import DesignSystem
import MarkRemoteFeatures
import MarkRemoteSecurity
import SwiftUI

/// Connection settings plus the package `SettingsView` for pairing state.
struct ConnectionSettingsView: View {
    @Bindable var environment: AppEnvironment

    @State private var hostDraft: String = ""
    @State private var portDraft: String = ""

    var body: some View {
        Form {
            Section("Рабочий стол") {
                LabeledContent("Адрес") {
                    TextField("127.0.0.1", text: $hostDraft)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .multilineTextAlignment(.trailing)
                }
                LabeledContent("Порт") {
                    TextField("8765", text: $portDraft)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                }
                Toggle("TLS (https)", isOn: $environment.useTLS)
                Button("Применить") { apply() }
                    .disabled(!isDraftValid)
            }

            Section("Текущее подключение") {
                Text(environment.baseURLDescription)
                    .font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
                if let error = environment.clientError {
                    Text(error).foregroundStyle(.red)
                }
            }

            if let client = environment.client {
                Section("Сопряжение и память") {
                    NavigationLink("Состояние устройства") {
                        SettingsFeatureView(
                            viewModel: SettingsViewModel(
                                deviceStore: LiveSettingsDeviceStore(
                                    credentialStore: environment.credentialStore
                                ),
                                statusService: LiveSettingsStatusService(client: client),
                                memoryClearer: LiveMemoryClearer(client: client)
                            )
                        )
                    }
                }
            }
        }
        .navigationTitle("Настройки")
        .onAppear {
            hostDraft = environment.host
            portDraft = String(environment.port)
        }
    }

    private var isDraftValid: Bool {
        guard let port = Int(portDraft), (1...65535).contains(port) else { return false }
        return !hostDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func apply() {
        guard let port = Int(portDraft) else { return }
        environment.host = hostDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        environment.port = port
        environment.forgetTokens()
    }
}
