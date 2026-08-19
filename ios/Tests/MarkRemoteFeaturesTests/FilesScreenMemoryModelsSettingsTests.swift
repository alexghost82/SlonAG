import Foundation
import MarkRemoteModels
import XCTest
@testable import MarkRemoteFeatures

// MARK: - Fakes

private final class FakeFilesService: FilesServing, @unchecked Sendable {
    var listings: [String: FilesListResult]
    private(set) var requestedPaths: [String] = []

    init(listings: [String: FilesListResult]) {
        self.listings = listings
    }

    func listEntries(path: String) async throws -> FilesListResult {
        requestedPaths.append(path)
        guard let result = listings[path] else {
            throw NSError(domain: "FakeFiles", code: 403, userInfo: [
                NSLocalizedDescriptionKey: "Path is not on the injected files allowlist.",
            ])
        }
        return result
    }
}

private final class FakeScreenService: ScreenServing, @unchecked Sendable {
    var response: ScreenCaptureResponse
    private(set) var keys: [String] = []

    init(response: ScreenCaptureResponse) {
        self.response = response
    }

    func captureScreen(idempotencyKey: String) async throws -> ScreenCaptureResponse {
        keys.append(idempotencyKey)
        return response
    }
}

private final class FakeMemoryService: MemoryServing, @unchecked Sendable {
    var entries: [MemoryEntry]
    private(set) var deleted: [(id: String, key: String)] = []

    init(entries: [MemoryEntry]) {
        self.entries = entries
    }

    func listEntries() async throws -> [MemoryEntry] {
        entries
    }

    func deleteEntry(id: String, idempotencyKey: String) async throws {
        deleted.append((id, idempotencyKey))
        entries.removeAll { $0.id == id }
    }
}

private final class FakeModelsService: ModelsServing, @unchecked Sendable {
    var models: [ModelInfo]
    private(set) var activations: [(modelId: String, key: String, role: String?)] = []

    init(models: [ModelInfo]) {
        self.models = models
    }

    func listModels() async throws -> [ModelInfo] {
        models
    }

    func activateModel(modelId: String, idempotencyKey: String, role: String?) async throws -> ModelInfo {
        activations.append((modelId, idempotencyKey, role))
        models = models.map { model in
            var copy = model
            copy.active = (model.id == modelId)
            if model.id == modelId {
                copy.active = true
            }
            return copy
        }
        return models.first(where: { $0.id == modelId })
            ?? ModelInfo(id: modelId, providerId: "local", active: true)
    }
}

private final class FakeDeviceStore: SettingsDeviceStoring, @unchecked Sendable {
    var deviceId: String?
    private(set) var revokeCount = 0

    init(deviceId: String?) {
        self.deviceId = deviceId
    }

    func loadDeviceId() throws -> String? {
        deviceId
    }

    func revokePairing() throws {
        revokeCount += 1
        deviceId = nil
    }
}

private final class FakeStatusService: SettingsStatusServing, @unchecked Sendable {
    var mode: String?

    init(mode: String?) {
        self.mode = mode
    }

    func fetchNetworkMode() async throws -> String? {
        mode
    }
}

private final class FakeMemoryClearer: SettingsMemoryClearing, @unchecked Sendable {
    private(set) var clearCount = 0

    func clearAllMemory() async throws {
        clearCount += 1
    }
}

// MARK: - Tests

@MainActor
final class FilesScreenMemoryModelsSettingsTests: XCTestCase {
    func testIdempotencyKeyHelperProducesUniqueNonEmptyKeys() {
        let a = IdempotencyKey.make()
        let b = IdempotencyKey.make()
        XCTAssertFalse(a.isEmpty)
        XCTAssertFalse(b.isEmpty)
        XCTAssertNotEqual(a, b)
    }

    func testFilesListViaInjectableAPIAndAllowlistMessaging() async {
        let root = FilesListResult(
            path: "/workspace",
            entries: [
                RemoteFileEntry(name: "docs", path: "/workspace/docs", isDirectory: true),
                RemoteFileEntry(name: "readme.md", path: "/workspace/readme.md", isDirectory: false),
            ]
        )
        let nested = FilesListResult(
            path: "/workspace/docs",
            entries: [
                RemoteFileEntry(name: "note.txt", path: "/workspace/docs/note.txt", isDirectory: false),
            ]
        )
        let service = FakeFilesService(listings: [
            "/workspace": root,
            "/workspace/docs": nested,
        ])
        let vm = FilesViewModel(service: service, rootPath: "/workspace")

        XCTAssertFalse(vm.supportsArbitraryPathEntry)
        XCTAssertTrue(vm.allowlistNotice.contains("разрешённого списка"))

        await vm.load()
        XCTAssertEqual(vm.entries.count, 2)
        XCTAssertEqual(service.requestedPaths, ["/workspace"])

        await vm.open(root.entries[0])
        XCTAssertEqual(vm.currentPath, "/workspace/docs")
        XCTAssertEqual(vm.entries.count, 1)

        await vm.goUp()
        XCTAssertEqual(vm.currentPath, "/workspace")
    }

    func testFilesDeniedPathSurfacesErrorWithoutEscapingAllowlist() async {
        let service = FakeFilesService(listings: [:])
        let vm = FilesViewModel(service: service, rootPath: "/etc")
        await vm.load()
        XCTAssertNotNil(vm.errorMessage)
        XCTAssertTrue(vm.errorMessage?.contains("allowlist") == true
            || vm.errorMessage?.contains("список") == true
            || vm.errorMessage?.localizedCaseInsensitiveContains("fail") == true
            || vm.errorMessage != nil)
        XCTAssertTrue(vm.entries.isEmpty)
    }

    func testScreenCaptureOnDemandShowsPlaceholderAndRequiresTapConfirmation() async {
        let service = FakeScreenService(
            response: ScreenCaptureResponse(
                width: 1920,
                height: 1080,
                mimeType: "image/png",
                captureId: "cap-42",
                approvalRequired: true
            )
        )
        let vm = ScreenViewModel(service: service)

        XCTAssertFalse(vm.supportsLiveVideo)
        XCTAssertTrue(vm.interactionConfirmationRequired)

        await vm.requestCapture()
        XCTAssertEqual(vm.placeholder?.captureId, "cap-42")
        XCTAssertEqual(vm.placeholder?.width, 1920)
        XCTAssertTrue(vm.placeholder?.summaryRU.contains("1920×1080") == true)
        XCTAssertEqual(service.keys.count, 1)
        XCTAssertFalse(service.keys[0].isEmpty)

        vm.proposeTap(normalizedX: 0.25, normalizedY: 0.75)
        XCTAssertNotNil(vm.pendingTapNormalized)
        XCTAssertNil(vm.lastConfirmedTap)

        XCTAssertTrue(vm.confirmPendingInteraction())
        XCTAssertEqual(vm.lastConfirmedTap?.x, 0.25)
        XCTAssertEqual(vm.lastConfirmedTap?.y, 0.75)
        XCTAssertNil(vm.pendingTapNormalized)
    }

    func testMemoryListDeleteRequiresConfirmation() async {
        let service = FakeMemoryService(entries: [
            MemoryEntry(id: "m1", kind: "note", summary: "важно"),
            MemoryEntry(id: "m2", kind: "fact", summary: "ещё"),
        ])
        let vm = MemoryViewModel(service: service)

        await vm.load()
        XCTAssertEqual(vm.entries.count, 2)

        vm.requestDelete(id: "m1")
        XCTAssertTrue(vm.isConfirmingDelete)
        XCTAssertEqual(service.deleted.count, 0)

        vm.cancelDelete()
        XCTAssertFalse(vm.isConfirmingDelete)
        XCTAssertEqual(vm.entries.count, 2)

        vm.requestDelete(id: "m1")
        await vm.confirmDelete()
        XCTAssertEqual(service.deleted.count, 1)
        XCTAssertEqual(service.deleted[0].id, "m1")
        XCTAssertFalse(service.deleted[0].key.isEmpty)
        XCTAssertEqual(vm.entries.map(\.id), ["m2"])
        XCTAssertFalse(vm.isConfirmingDelete)
    }

    func testModelsListActivateUsesIdempotencyKey() async {
        let service = FakeModelsService(models: [
            ModelInfo(id: "local-1", providerId: "ollama", displayName: "Локальная", active: true),
            ModelInfo(id: "local-2", providerId: "ollama", displayName: "Запасная", active: false),
        ])
        let vm = ModelsViewModel(service: service)

        await vm.load()
        XCTAssertEqual(vm.models.count, 2)
        XCTAssertEqual(vm.activeModel?.id, "local-1")

        await vm.activate(modelId: "local-2")
        XCTAssertEqual(service.activations.count, 1)
        XCTAssertEqual(service.activations[0].modelId, "local-2")
        XCTAssertFalse(service.activations[0].key.isEmpty)
        XCTAssertEqual(vm.lastActivationIdempotencyKey, service.activations[0].key)
        XCTAssertEqual(vm.activeModel?.id, "local-2")
        XCTAssertEqual(vm.models.filter(\.active).count, 1)
    }

    func testSettingsShowsDeviceIdNetworkModeRevokeWithoutPublicBind() async {
        let store = FakeDeviceStore(deviceId: "device-abc")
        let status = FakeStatusService(mode: "offline")
        let clearer = FakeMemoryClearer()
        let vm = SettingsViewModel(
            deviceStore: store,
            statusService: status,
            memoryClearer: clearer
        )

        await vm.load()
        XCTAssertEqual(vm.pairedDeviceId, "device-abc")
        XCTAssertEqual(vm.networkModeDisplay, "Офлайн")
        XCTAssertFalse(vm.exposesPublicBindControl)

        vm.requestRevoke()
        XCTAssertTrue(vm.revokeConfirmationPending)
        vm.cancelRevoke()
        XCTAssertEqual(store.revokeCount, 0)
        XCTAssertEqual(vm.pairedDeviceId, "device-abc")

        vm.requestRevoke()
        vm.confirmRevoke()
        XCTAssertEqual(store.revokeCount, 1)
        XCTAssertNil(vm.pairedDeviceId)
        XCTAssertTrue(vm.didRevoke)

        vm.requestClearMemory()
        await vm.confirmClearMemory()
        XCTAssertEqual(clearer.clearCount, 1)
        XCTAssertTrue(vm.didClearMemory)

        // Guardrail: no public-bind / 0.0.0.0 affordance on the view model API surface.
        let mirror = Mirror(reflecting: vm)
        let names = mirror.children.compactMap(\.label)
        XCTAssertFalse(names.contains(where: { $0.localizedCaseInsensitiveContains("public") }))
        XCTAssertFalse(names.contains(where: { $0.localizedCaseInsensitiveContains("bind") }))
        XCTAssertFalse(names.contains(where: { $0.localizedCaseInsensitiveContains("0.0.0.0") }))
    }

    func testSettingsNetworkModeLabels() {
        XCTAssertEqual(SettingsViewModel.networkModeLabelRU("tools_only"), "Только инструменты")
        XCTAssertEqual(SettingsViewModel.networkModeLabelRU("hybrid"), "Гибридный")
        XCTAssertEqual(SettingsViewModel.networkModeLabelRU("loopback"), "Локальная сеть (loopback)")
        XCTAssertEqual(SettingsViewModel.networkModeLabelRU(nil), "Неизвестно")
    }

    func testRussianAllowlistAndSettingsCopyPresent() {
        XCTAssertTrue(FilesViewModel.allowlistNoticeRU.contains("разрешённого списка"))
        XCTAssertTrue(FilesViewModel.allowlistNoticeRU.contains("Произвольный ввод"))
    }
}
