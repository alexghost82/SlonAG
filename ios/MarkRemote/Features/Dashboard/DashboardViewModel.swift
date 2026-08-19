import DesignSystem
import Foundation
import Observation

/// View-model for the main remote dashboard panel.
@MainActor
@Observable
public final class DashboardViewModel {
    public private(set) var snapshot: DashboardSnapshot
    public private(set) var isBusy: Bool = false
    public private(set) var errorMessage: String?
    public private(set) var lastAction: AssistantControlAction?

    private let controller: any DashboardControlling

    public init(
        controller: any DashboardControlling,
        initial: DashboardSnapshot = DashboardSnapshot(online: false)
    ) {
        self.controller = controller
        self.snapshot = initial
    }

    public var connectionStatus: MRConnectionStatus {
        snapshot.online ? .online : .offline
    }

    public var providerText: String {
        snapshot.providerId?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
            ?? "Провайдер не выбран"
    }

    public var modelText: String {
        snapshot.modelId?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
            ?? "Модель не выбрана"
    }

    public var networkModeText: String {
        snapshot.networkMode?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
            ?? "Режим сети неизвестен"
    }

    public var runtimeText: String {
        let value = snapshot.runtimeStatus.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "Состояние runtime неизвестно" : value
    }

    public var micIndicatorText: String {
        snapshot.micActive ? "Микрофон активен" : "Микрофон выключен"
    }

    public func refresh() async {
        guard !isBusy else { return }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        do {
            snapshot = try await controller.refreshStatus()
        } catch {
            errorMessage = "Не удалось обновить статус рабочего стола."
        }
    }

    public func start() async {
        await perform(.start)
    }

    public func pause() async {
        await perform(.pause)
    }

    public func stop() async {
        await perform(.stop)
    }

    private func perform(_ action: AssistantControlAction) async {
        guard !isBusy else { return }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        do {
            try await controller.perform(action)
            lastAction = action
            snapshot = try await controller.refreshStatus()
        } catch {
            errorMessage = Self.userFacingError(for: action)
        }
    }

    private static func userFacingError(for action: AssistantControlAction) -> String {
        switch action {
        case .start: "Не удалось запустить ассистента."
        case .pause: "Не удалось поставить ассистента на паузу."
        case .stop: "Не удалось остановить ассистента."
        }
    }
}

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
