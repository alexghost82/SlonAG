import Foundation
import MarkRemoteFeatures
import MarkRemoteModels
import MarkRemoteNetworking
import MarkRemoteSecurity

enum LiveServiceError: LocalizedError {
    case unsupported(String)

    var errorDescription: String? {
        switch self {
        case let .unsupported(message): message
        }
    }
}

struct LivePairingService: PairingServing {
    let client: DesktopAPIClient
    let credentialStore: any CredentialStore

    func startPairing(idempotencyKey: String) async throws -> PairingSession {
        PairingSession(
            try await client.startPairing(PairingStartRequest(idempotencyKey: idempotencyKey))
        )
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
        _ = try await client.revokePairing(
            PairingRevokeRequest(idempotencyKey: UUID().uuidString)
        )
        try credentialStore.delete()
    }

    func listPairedDevices() async -> [PairedDeviceInfo] {
        guard let credentials = try? credentialStore.load() else { return [] }
        return [PairedDeviceInfo(deviceId: credentials.deviceId, deviceName: "Рабочий стол")]
    }
}

struct LiveDashboardController: DashboardControlling {
    let client: DesktopAPIClient

    func refreshStatus() async throws -> DashboardSnapshot {
        DashboardSnapshot(status: try await client.getStatus(), runtimeStatus: "подключено")
    }

    func perform(_ action: AssistantControlAction) async throws {
        try await client.controlRuntime(action: action.rawValue)
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
        let response = try await client.getMemory()
        for entry in response.entries {
            try await client.deleteMemory(
                id: entry.id,
                body: MemoryDeleteRequest(idempotencyKey: UUID().uuidString)
            )
        }
    }
}

struct LiveChatService: ChatStreamingServing {
    let client: DesktopAPIClient

    func streamChat(
        message: String,
        conversationId: String?,
        idempotencyKey: String
    ) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let event = try await client.sendChat(
                        ChatRequest(
                            message: message,
                            idempotencyKey: idempotencyKey,
                            conversationId: conversationId
                        )
                    )
                    continuation.yield(event)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

struct LiveModelsService: ModelsServing {
    let client: DesktopAPIClient

    func listModels() async throws -> [ModelInfo] {
        try await client.listModels().models
    }

    func activateModel(
        modelId: String,
        idempotencyKey: String,
        role: String?
    ) async throws -> ModelInfo {
        try await client.activateModel(
            ModelsActivateRequest(
                modelId: modelId,
                idempotencyKey: idempotencyKey,
                role: role
            )
        )
    }
}

struct LiveMemoryService: MemoryServing {
    let client: DesktopAPIClient

    func listEntries() async throws -> [MemoryEntry] {
        try await client.getMemory().entries
    }

    func deleteEntry(id: String, idempotencyKey: String) async throws {
        try await client.deleteMemory(
            id: id,
            body: MemoryDeleteRequest(idempotencyKey: idempotencyKey)
        )
    }
}

struct LiveFilesService: FilesServing {
    let client: DesktopAPIClient

    func listEntries(path: String) async throws -> FilesListResult {
        let response = try await client.listFiles(path: path)
        return FilesListResult(
            path: response.path,
            entries: response.entries.map {
                RemoteFileEntry(
                    name: $0.name,
                    path: $0.path,
                    isDirectory: $0.isDirectory
                )
            }
        )
    }

    func uploadFile(url: URL, directory: String) async throws {
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed { url.stopAccessingSecurityScopedResource() }
        }
        let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        guard values.isRegularFile == true else {
            throw LiveServiceError.unsupported("Можно загрузить только обычный файл.")
        }
        guard (values.fileSize ?? 0) <= 10 * 1024 * 1024 else {
            throw LiveServiceError.unsupported("Максимальный размер файла — 10 МБ.")
        }
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        _ = try await client.uploadFile(
            FileUploadRequest(
                directory: directory,
                filename: url.lastPathComponent,
                contentBase64: data.base64EncodedString(),
                idempotencyKey: UUID().uuidString
            )
        )
    }
}
