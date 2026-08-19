import DesignSystem
import MarkRemoteFeatures
import MarkRemoteModels
import MarkRemoteNetworking
import MarkRemoteSecurity
import SwiftUI

public struct MarkRemoteApp: App {
    @State private var environment = AppEnvironment()

    public init() {}

    public var body: some Scene {
        WindowGroup {
            MarkRemoteRootView(environment: environment)
        }
    }
}

public struct MarkRemoteRootView: View {
    @State private var environment: AppEnvironment

    public init(environment: AppEnvironment = AppEnvironment()) {
        _environment = State(initialValue: environment)
    }

    public var body: some View {
        TabView {
            NavigationStack {
                configured { client in
                    DesktopControlView(
                        client: client,
                        eventsClient: environment.eventsClient
                    )
                }
            }
            .tabItem {
                Label("Управление", systemImage: "dot.radiowaves.left.and.right")
            }
            .accessibilityIdentifier("tab.control")

            NavigationStack {
                configured { client in
                    ConversationView(
                        viewModel: ConversationViewModel(
                            chatClient: LiveChatService(client: client)
                        )
                    )
                }
            }
            .tabItem {
                Label("Активность", systemImage: "terminal")
            }
            .accessibilityIdentifier("tab.activity")

            NavigationStack {
                RemoteFeaturesView(environment: environment)
            }
            .tabItem {
                Label("Удалённо", systemImage: "rectangle.connected.to.line.below")
            }
            .accessibilityIdentifier("tab.remote")

            NavigationStack {
                ConnectionSettingsView(environment: environment)
            }
            .tabItem {
                Label("Настройки", systemImage: "gearshape")
            }
            .accessibilityIdentifier("tab.settings")
        }
        .tint(MRColor.accent)
        .preferredColorScheme(.dark)
    }

    @ViewBuilder
    private func configured<Content: View>(
        @ViewBuilder content: (DesktopAPIClient) -> Content
    ) -> some View {
        if let client = environment.client {
            content(client)
        } else {
            MREmptyState(
                title: "Соединение не настроено",
                message: environment.clientError ?? "Проверьте адрес рабочего стола.",
                systemImage: "exclamationmark.triangle"
            )
            .background(MRColor.background)
        }
    }
}

private struct RemoteFeaturesView: View {
    let environment: AppEnvironment

    var body: some View {
        Group {
            if let client = environment.client {
                List {
                    destination("Сопряжение", icon: "qrcode") {
                        PairingView(
                            viewModel: PairingViewModel(
                                service: LivePairingService(
                                    client: client,
                                    credentialStore: environment.credentialStore
                                )
                            )
                        )
                    }
                    destination("Экран", icon: "rectangle.on.rectangle") {
                        ScreenView(viewModel: ScreenViewModel(service: LiveScreenService(client: client)))
                    }
                    destination("Голос", icon: "mic") {
                        VoiceView(
                            controller: VoiceSessionController(
                                capturer: NativeSpeechCapturer(),
                                player: NativeSpeechPlayer(),
                                transcriptHandler: { transcript in
                                    try await client.sendChat(
                                        ChatRequest(
                                            message: transcript,
                                            idempotencyKey: UUID().uuidString
                                        )
                                    ).delta
                                }
                            )
                        )
                    }
                    destination("Задачи", icon: "checklist") {
                        TasksListView(
                            viewModel: TasksListViewModel(
                                client: DesktopAPITasksClient(api: client)
                            )
                        )
                    }
                    destination("Подтверждения", icon: "hand.raised") {
                        ApprovalsView(
                            viewModel: ApprovalsViewModel(
                                client: DesktopAPIApprovalsClient(api: client),
                                biometrics: LocalAuthenticationGate()
                            )
                        )
                    }
                    destination("Модели", icon: "cpu") {
                        ModelsView(viewModel: ModelsViewModel(service: LiveModelsService(client: client)))
                    }
                    destination("Память", icon: "brain.head.profile") {
                        MemoryView(viewModel: MemoryViewModel(service: LiveMemoryService(client: client)))
                    }
                    destination("Файлы", icon: "folder") {
                        FilesView(viewModel: FilesViewModel(service: LiveFilesService(client: client)))
                    }
                }
                .scrollContentBackground(.hidden)
                .background(MRColor.background)
            } else {
                MREmptyState(
                    title: "Нет подключения",
                    message: "Настройте адрес рабочего стола.",
                    systemImage: "network.slash"
                )
            }
        }
        .navigationTitle("Удалённо")
    }

    private func destination<Content: View>(
        _ title: String,
        icon: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        NavigationLink(destination: content()) {
            Label(title, systemImage: icon)
                .font(MRTypography.body)
                .foregroundStyle(MRColor.label)
                .frame(minHeight: 44)
        }
    }
}

#Preview("Slon") {
    MarkRemoteRootView()
}
