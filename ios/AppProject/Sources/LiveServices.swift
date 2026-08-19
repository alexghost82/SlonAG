import Foundation
import MarkRemoteFeatures
import MarkRemoteModels
import MarkRemoteNetworking
import MarkRemoteSecurity

enum LiveServiceError: LocalizedError {
    case notConfigured
    case unsupported(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            "Соединение с рабочим столом не настроено."
        case let .unsupported(message):
            message
        }
    }
}

/// Pairing against the live Desktop Control API, persisting the issued
/// device credential in the Keychain.
struct LivePairingService: PairingServing {
    let client: DesktopAPIClient
    let credentialStore: any CredentialStore

    func startPairing(idempotencyKey: String) async throws -> PairingSession {
        let response = try await client.startPairing(
            PairingStartRequest(idempotencyKey: idempotencyKey)
        )
        return PairingSession(response)
    }

    func completePairing(
        code: String,
        deviceName: String,
        idempotencyKey: String
    ) async throws -> PairedDeviceInfo {
        let response = try await client.completePairing(
            PairingCompleteRequest(
                code: code,
                deviceName: deviceName,
                idempotencyKey: idempotencyKey
            )
        )
        try credentialStore.save(
            DeviceCredentials(
                deviceId: response.deviceId,
                deviceSecret: response.deviceSecret,
                expiresAt: response.expiresAt
            )
        )
        return PairedDeviceInfo(deviceId: response.deviceId, deviceName: deviceName)
    }

    func unpair(deviceId: String) async throws {
        try credentialStore.delete()
    }

    func listPairedDevices() async -> [PairedDeviceInfo] {
        guard let credentials = try? credentialStore.load() else { return [] }
        return [PairedDeviceInfo(deviceId: credentials.deviceId, deviceName: "Рабочий стол")]
    }
}

/// Dashboard status from `GET /v1/status`.
///
/// Runtime start/pause/stop is not exposed by the Desktop Control API yet,
/// so those actions surface an explicit error instead of faking success.
struct LiveDashboardController: DashboardControlling {
    let client: DesktopAPIClient
    let credentialStore: any CredentialStore

    func refreshStatus() async throws -> DashboardSnapshot {
        do {
            let status = try await client.getStatus()
            return DashboardSnapshot(status: status, runtimeStatus: "подключено")
        } catch DesktopAPIClientError.missingAccessToken {
            return DashboardSnapshot(
                online: false,
                paired: false,
                runtimeStatus: "нет сопряжения"
            )
        }
    }

    func perform(_ action: AssistantControlAction) async throws {
        throw LiveServiceError.unsupported(
            "Управление сессией пока доступно только на рабочем столе."
        )
    }
}

struct LiveScreenService: ScreenServing {
    let client: DesktopAPIClient

    func captureScreen(idempotencyKey: String) async throws -> ScreenCaptureResponse {
        try await client.captureScreen(ScreenCaptureRequest(idempotencyKey: idempotencyKey))
    }
}

struct LiveSettingsDeviceStore: SettingsDeviceStoring {
    let credentialStore: any CredentialStore

    func loadDeviceId() throws -> String? {
        try credentialStore.load()?.deviceId
    }

    func revokePairing() throws {
        try credentialStore.delete()
    }
}

struct LiveSettingsStatusService: SettingsStatusServing {
    let client: DesktopAPIClient

    func fetchNetworkMode() async throws -> String? {
        try await client.getStatus().networkMode
    }
}

struct LiveMemoryClearer: SettingsMemoryClearing {
    let client: DesktopAPIClient

    func clearAllMemory() async throws {
        let memory = try await client.getMemory()
        for entry in memory.entries {
            try await client.deleteMemory(
                id: entry.id,
                body: MemoryDeleteRequest(idempotencyKey: UUID().uuidString)
            )
        }
    }
}
