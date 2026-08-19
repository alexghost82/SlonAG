import DesignSystem
import MarkRemoteFeatures
import SwiftUI

struct ConnectionSettingsView: View {
    @Bindable var environment: AppEnvironment
    @State private var hostDraft = ""
    @State private var portDraft = ""
    @State private var fingerprintDraft = ""
    @State private var accountService = AppwriteAccountService()
    @State private var cloudPreferences = CloudPreferences()
    @State private var settingsRepository: AppwriteSettingsRepository?
    @State private var bonjourBrowser = BonjourBrowser()
    @State private var discoveredServices: [BonjourBrowser.Service] = []

    var body: some View {
        Form {
            Section("Рабочий стол") {
                LabeledContent("Адрес") {
                    TextField("127.0.0.1", text: $hostDraft)
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        #endif
                        .multilineTextAlignment(.trailing)
                        .accessibilityIdentifier("settings.host")
                }
                LabeledContent("Порт") {
                    TextField("8765", text: $portDraft)
                        .multilineTextAlignment(.trailing)
                        #if os(iOS)
                        .keyboardType(.numberPad)
                        #endif
                        .accessibilityIdentifier("settings.port")
                }
                Toggle("TLS (https)", isOn: $environment.useTLS)
                    .accessibilityIdentifier("settings.tls")
                if environment.useTLS {
                    TextField("SHA-256 fingerprint", text: $fingerprintDraft)
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        #endif
                        .font(MRTypography.caption)
                        .accessibilityIdentifier("settings.certificate_fingerprint")
                }
                Button("Применить") { apply() }
                    .disabled(!isDraftValid)
                    .accessibilityIdentifier("settings.apply")
            }

            Section("Текущее подключение") {
                Text(environment.baseURLDescription)
                    .font(MRTypography.footnote)
                    .foregroundStyle(MRColor.secondaryLabel)
                if let error = environment.clientError {
                    Text(error)
                        .font(MRTypography.footnote)
                        .foregroundStyle(MRColor.danger)
                }
            }

            Section("Найденные Mac") {
                if discoveredServices.isEmpty {
                    Text("Поиск сервисов Slon в локальной сети…")
                        .foregroundStyle(MRColor.secondaryLabel)
                } else {
                    ForEach(discoveredServices, id: \.name) { service in
                        Button {
                            guard let host = service.host, let port = service.port else {
                                return
                            }
                            hostDraft = host
                            portDraft = String(port)
                            environment.useTLS = service.usesTLS
                            fingerprintDraft = service.certificateFingerprint ?? ""
                            apply()
                        } label: {
                            LabeledContent(
                                service.name,
                                value: service.host.map {
                                    "\($0):\(service.port ?? 8765)"
                                } ?? "Разрешение адреса…"
                            )
                        }
                        .disabled(
                            service.host == nil
                                || service.port == nil
                                || !service.usesTLS
                                || service.certificateFingerprint == nil
                        )
                    }
                }
            }

            Section("Аккаунт и синхронизация") {
                if !accountService.isConfigured {
                    Text("Appwrite не настроен. Добавьте APPWRITE_* значения в конфигурацию приложения.")
                        .font(MRTypography.footnote)
                        .foregroundStyle(MRColor.secondaryLabel)
                } else if accountService.isSignedIn {
                    LabeledContent("Apple ID", value: accountService.displayName ?? "Подключён")
                    Toggle("Уменьшать анимацию", isOn: $cloudPreferences.reducedMotion)
                    Toggle("Компактный монитор", isOn: $cloudPreferences.compactMonitor)
                    Toggle(
                        "Микрофон включён при запуске",
                        isOn: $cloudPreferences.defaultMicrophoneEnabled
                    )
                    Button("Синхронизировать") {
                        Task { await saveCloudPreferences() }
                    }
                    Button("Выйти", role: .destructive) {
                        Task { await accountService.signOut() }
                    }
                } else {
                    Button("Войти с Apple") {
                        Task {
                            await accountService.signInWithApple()
                            await loadCloudPreferences()
                        }
                    }
                    .disabled(accountService.isBusy)
                    .accessibilityIdentifier("settings.sign_in_apple")
                }
                if let error = accountService.errorMessage {
                    Text(error)
                        .font(MRTypography.footnote)
                        .foregroundStyle(MRColor.danger)
                }
            }

            if let client = environment.client {
                Section("Устройство") {
                    NavigationLink("Сопряжение и память") {
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
        .scrollContentBackground(.hidden)
        .background(MRColor.background)
        .navigationTitle("Настройки")
        .onAppear {
            hostDraft = environment.host
            portDraft = String(environment.port)
            fingerprintDraft = environment.certificateFingerprint
            bonjourBrowser.onUpdate = { discoveredServices = $0 }
            bonjourBrowser.start()
        }
        .onDisappear { bonjourBrowser.stop() }
        .task {
            await accountService.restoreSession()
            await loadCloudPreferences()
        }
    }

    private var isDraftValid: Bool {
        guard let port = Int(portDraft), (1...65_535).contains(port) else { return false }
        if environment.useTLS, fingerprintDraft.filter(\.isHexDigit).count != 64 {
            return false
        }
        return !hostDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func apply() {
        guard let port = Int(portDraft) else { return }
        environment.certificateFingerprint = fingerprintDraft
        environment.host = hostDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        environment.port = port
        environment.forgetTokens()
    }

    private func loadCloudPreferences() async {
        guard let userId = accountService.userId else { return }
        let repository = AppwriteSettingsRepository(accountService: accountService)
        settingsRepository = repository
        cloudPreferences = await repository.load(userId: userId)
    }

    private func saveCloudPreferences() async {
        guard let userId = accountService.userId, let settingsRepository else { return }
        var next = cloudPreferences
        next.updatedAt = Date().timeIntervalSince1970
        cloudPreferences = next
        try? await settingsRepository.save(next, userId: userId)
    }
}
