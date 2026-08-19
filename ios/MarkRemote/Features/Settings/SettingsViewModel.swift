import Foundation
import Observation

@MainActor
@Observable
public final class SettingsViewModel {
    public private(set) var pairedDeviceId: String?
    public private(set) var networkMode: String?
    public private(set) var isLoading = false
    public private(set) var errorMessage: String?
    public private(set) var revokeConfirmationPending = false
    public private(set) var clearMemoryConfirmationPending = false
    public private(set) var didRevoke = false
    public private(set) var didClearMemory = false

    private let deviceStore: any SettingsDeviceStoring
    private let statusService: any SettingsStatusServing
    private let memoryClearer: (any SettingsMemoryClearing)?

    public init(
        deviceStore: any SettingsDeviceStoring,
        statusService: any SettingsStatusServing,
        memoryClearer: (any SettingsMemoryClearing)? = nil
    ) {
        self.deviceStore = deviceStore
        self.statusService = statusService
        self.memoryClearer = memoryClearer
    }

    /// Network mode labels shown in UI. Display-only — no bind controls.
    public static func networkModeLabelRU(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "Неизвестно" }
        switch raw.lowercased() {
        case "offline": return "Офлайн"
        case "tools_only": return "Только инструменты"
        case "hybrid": return "Гибридный"
        case "loopback", "local": return "Локальная сеть (loopback)"
        default: return raw
        }
    }

    public var networkModeDisplay: String {
        Self.networkModeLabelRU(networkMode)
    }

    /// Explicitly absent: Settings must never offer public / 0.0.0.0 listen.
    public var exposesPublicBindControl: Bool { false }

    public func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            pairedDeviceId = try deviceStore.loadDeviceId()
            networkMode = try await statusService.fetchNetworkMode()
        } catch {
            errorMessage = "Не удалось загрузить настройки: \(error.localizedDescription)"
        }
    }

    public func requestRevoke() {
        revokeConfirmationPending = true
    }

    public func cancelRevoke() {
        revokeConfirmationPending = false
    }

    public func confirmRevoke() {
        do {
            try deviceStore.revokePairing()
            pairedDeviceId = nil
            didRevoke = true
            revokeConfirmationPending = false
        } catch {
            errorMessage = "Не удалось отозвать устройство: \(error.localizedDescription)"
            revokeConfirmationPending = false
        }
    }

    public func requestClearMemory() {
        clearMemoryConfirmationPending = true
    }

    public func cancelClearMemory() {
        clearMemoryConfirmationPending = false
    }

    public func confirmClearMemory() async {
        guard let memoryClearer else {
            clearMemoryConfirmationPending = false
            return
        }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await memoryClearer.clearAllMemory()
            didClearMemory = true
            clearMemoryConfirmationPending = false
        } catch {
            errorMessage = "Не удалось очистить память: \(error.localizedDescription)"
            clearMemoryConfirmationPending = false
        }
    }
}
