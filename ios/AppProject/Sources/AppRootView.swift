import DesignSystem
import MarkRemoteFeatures
import SwiftUI

struct AppRootView: View {
    let environment: AppEnvironment

    var body: some View {
        TabView {
            NavigationStack {
                dashboardTab
            }
            .tabItem { Label("Обзор", systemImage: "laptopcomputer") }

            NavigationStack {
                pairingTab
            }
            .tabItem { Label("Сопряжение", systemImage: "qrcode") }

            NavigationStack {
                screenTab
            }
            .tabItem { Label("Экран", systemImage: "rectangle.on.rectangle") }

            NavigationStack {
                ConnectionSettingsView(environment: environment)
            }
            .tabItem { Label("Настройки", systemImage: "gearshape") }
        }
        .tint(MRColor.accent)
    }

    @ViewBuilder
    private var dashboardTab: some View {
        if let client = environment.client {
            DashboardView(
                viewModel: DashboardViewModel(
                    controller: LiveDashboardController(
                        client: client,
                        credentialStore: environment.credentialStore
                    )
                )
            )
            .navigationTitle("Обзор")
        } else {
            notConfigured
        }
    }

    @ViewBuilder
    private var pairingTab: some View {
        if let client = environment.client {
            PairingView(
                viewModel: PairingViewModel(
                    service: LivePairingService(
                        client: client,
                        credentialStore: environment.credentialStore
                    )
                )
            )
            .navigationTitle("Сопряжение")
        } else {
            notConfigured
        }
    }

    @ViewBuilder
    private var screenTab: some View {
        if let client = environment.client {
            LiveScreenTabView(environment: environment, client: client)
                .navigationTitle("Экран")
        } else {
            notConfigured
        }
    }

    private var notConfigured: some View {
        VStack(spacing: MRSpacing.md) {
            Image(systemName: "exclamationmark.triangle")
                .font(.largeTitle)
            Text(environment.clientError ?? "Проверьте адрес рабочего стола в настройках.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
        }
        .padding(MRSpacing.lg)
        .navigationTitle("Не настроено")
    }
}
