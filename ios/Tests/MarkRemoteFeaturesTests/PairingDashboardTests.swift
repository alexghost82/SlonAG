import XCTest
import DesignSystem
import MarkRemoteModels
@testable import MarkRemoteFeatures

// MARK: - Fakes

private final class FakePairingService: PairingServing, @unchecked Sendable {
    var startCalls = 0
    var completeCalls = 0
    var unpairCalls: [String] = []
    var devices: [PairedDeviceInfo] = []
    var nextSession = PairingSession(
        code: "654321",
        expiresAt: 1_700_000_000,
        qrPayload: "mark-remote://pair?code=654321&host=127.0.0.1"
    )
    var shouldFailStart = false
    var shouldFailUnpair = false

    func startPairing(idempotencyKey: String) async throws -> PairingSession {
        startCalls += 1
        XCTAssertFalse(idempotencyKey.isEmpty)
        if shouldFailStart {
            throw FakeError.boom
        }
        return nextSession
    }

    func completePairing(code: String, deviceName: String, idempotencyKey: String) async throws -> PairedDeviceInfo {
        completeCalls += 1
        let device = PairedDeviceInfo(deviceId: "dev_\(code)", deviceName: deviceName)
        devices.append(device)
        return device
    }

    func unpair(deviceId: String) async throws {
        unpairCalls.append(deviceId)
        if shouldFailUnpair {
            throw FakeError.boom
        }
        devices.removeAll { $0.deviceId == deviceId }
    }

    func listPairedDevices() async -> [PairedDeviceInfo] {
        devices
    }
}

private final class FakeDashboardController: DashboardControlling, @unchecked Sendable {
    var actions: [AssistantControlAction] = []
    var refreshCount = 0
    var snapshot = DashboardSnapshot(
        online: true,
        paired: true,
        providerId: "ollama",
        modelId: "llama3.2",
        networkMode: "полностью локальный",
        runtimeStatus: "ожидание",
        micActive: false,
        activeTasks: 1,
        pendingApprovals: 0
    )
    var shouldFailAction = false

    func refreshStatus() async throws -> DashboardSnapshot {
        refreshCount += 1
        return snapshot
    }

    func perform(_ action: AssistantControlAction) async throws {
        if shouldFailAction {
            throw FakeError.boom
        }
        actions.append(action)
        switch action {
        case .start:
            snapshot.runtimeStatus = "работает"
            snapshot.online = true
        case .pause:
            snapshot.runtimeStatus = "пауза"
        case .stop:
            snapshot.runtimeStatus = "остановлен"
            snapshot.micActive = false
        }
    }
}

private enum FakeError: Error {
    case boom
}

// MARK: - Suite

@MainActor
final class PairingDashboardTests: XCTestCase {
    func testStartPairingExposesOneTimeCodeAndQRPayloadText() async {
        let service = FakePairingService()
        let vm = PairingViewModel(service: service)

        await vm.startPairing()

        XCTAssertEqual(service.startCalls, 1)
        XCTAssertEqual(vm.oneTimeCode, "654321")
        XCTAssertEqual(vm.qrPayload, "mark-remote://pair?code=654321&host=127.0.0.1")
        XCTAssertEqual(vm.expiresAt, 1_700_000_000)
        XCTAssertNil(vm.errorMessage)
        XCTAssertFalse(vm.qrPayload.contains("\0"))
    }

    func testCompletePairingAddsDeviceAndClearsSession() async {
        let service = FakePairingService()
        let vm = PairingViewModel(service: service)
        await vm.startPairing()
        vm.deviceNameInput = "iPhone Тест"

        await vm.completePairing()

        XCTAssertEqual(service.completeCalls, 1)
        XCTAssertEqual(vm.pairedDevices.count, 1)
        XCTAssertEqual(vm.pairedDevices.first?.deviceName, "iPhone Тест")
        XCTAssertEqual(vm.pairedDevices.first?.deviceId, "dev_654321")
        XCTAssertTrue(vm.oneTimeCode.isEmpty)
        XCTAssertTrue(vm.qrPayload.isEmpty)
    }

    func testUnpairRemovesDevice() async {
        let service = FakePairingService()
        service.devices = [
            PairedDeviceInfo(deviceId: "dev_a", deviceName: "Mac mini"),
            PairedDeviceInfo(deviceId: "dev_b", deviceName: "MacBook"),
        ]
        let vm = PairingViewModel(service: service)
        await vm.refreshPairedDevices()
        XCTAssertEqual(vm.pairedDevices.count, 2)

        await vm.unpair(deviceId: "dev_a")

        XCTAssertEqual(service.unpairCalls, ["dev_a"])
        XCTAssertEqual(vm.pairedDevices.map(\.deviceId), ["dev_b"])
    }

    func testStartPairingFailureSurfacesRussianError() async {
        let service = FakePairingService()
        service.shouldFailStart = true
        let vm = PairingViewModel(service: service)

        await vm.startPairing()

        XCTAssertEqual(vm.errorMessage, "Не удалось выполнить сопряжение. Попробуйте ещё раз.")
        XCTAssertTrue(vm.oneTimeCode.isEmpty)
    }

    func testPairingStateNeverHoldsAIKeys() async {
        let service = FakePairingService()
        let vm = PairingViewModel(service: service)
        await vm.startPairing()
        await vm.completePairing()

        let dump = "\(vm.oneTimeCode)|\(vm.qrPayload)|\(vm.pairedDevices)"
        XCTAssertFalse(dump.lowercased().contains("api_key"))
        XCTAssertFalse(dump.lowercased().contains("sk-"))
        XCTAssertFalse(dump.lowercased().contains("openrouter"))
    }

    func testRefreshMapsStatusFieldsAndOnlineBadge() async {
        let controller = FakeDashboardController()
        let vm = DashboardViewModel(controller: controller)

        await vm.refresh()

        XCTAssertEqual(controller.refreshCount, 1)
        XCTAssertEqual(vm.connectionStatus, .online)
        XCTAssertEqual(vm.providerText, "ollama")
        XCTAssertEqual(vm.modelText, "llama3.2")
        XCTAssertEqual(vm.networkModeText, "полностью локальный")
        XCTAssertEqual(vm.runtimeText, "ожидание")
        XCTAssertEqual(vm.micIndicatorText, "Микрофон выключен")
        XCTAssertEqual(MRConnectionStatus.online.titleRU, "Онлайн")
        XCTAssertEqual(MRConnectionStatus.offline.titleRU, "Офлайн")
    }

    func testMissingProviderModelUseRussianPlaceholders() async {
        let controller = FakeDashboardController()
        controller.snapshot = DashboardSnapshot(
            online: false,
            providerId: "  ",
            modelId: nil,
            networkMode: nil
        )
        let vm = DashboardViewModel(controller: controller)

        await vm.refresh()

        XCTAssertEqual(vm.connectionStatus, .offline)
        XCTAssertEqual(vm.providerText, "Провайдер не выбран")
        XCTAssertEqual(vm.modelText, "Модель не выбрана")
        XCTAssertEqual(vm.networkModeText, "Режим сети неизвестен")
    }

    func testStartPauseStopCallInjectableController() async {
        let controller = FakeDashboardController()
        let vm = DashboardViewModel(controller: controller)

        await vm.start()
        await vm.pause()
        await vm.stop()

        XCTAssertEqual(controller.actions, [.start, .pause, .stop])
        XCTAssertEqual(vm.lastAction, .stop)
        XCTAssertEqual(vm.runtimeText, "остановлен")
        XCTAssertNil(vm.errorMessage)
    }

    func testControlFailureSurfacesRussianError() async {
        let controller = FakeDashboardController()
        controller.shouldFailAction = true
        let vm = DashboardViewModel(controller: controller)

        await vm.start()

        XCTAssertEqual(vm.errorMessage, "Не удалось запустить ассистента.")
        XCTAssertTrue(controller.actions.isEmpty)
    }

    func testDashboardSnapshotFromStatusResponse() {
        let status = StatusResponse(
            online: true,
            paired: true,
            providerId: "openai",
            modelId: "gpt-test",
            networkMode: "облачный",
            activeTasks: 2,
            pendingApprovals: 1
        )
        let snap = DashboardSnapshot(status: status, runtimeStatus: "placeholder", micActive: true)
        XCTAssertTrue(snap.online)
        XCTAssertEqual(snap.providerId, "openai")
        XCTAssertEqual(snap.runtimeStatus, "placeholder")
        XCTAssertTrue(snap.micActive)
    }

    func testPairingViewInstantiates() {
        let vm = PairingViewModel(service: FakePairingService())
        let view = PairingView(viewModel: vm)
        XCTAssertNotNil(view.body)
    }

    func testDashboardViewInstantiates() {
        let vm = DashboardViewModel(controller: FakeDashboardController())
        let view = DashboardView(viewModel: vm)
        XCTAssertNotNil(view.body)
    }

    func testPairingSessionMapsFromDTO() {
        let dto = PairingStartResponse(code: "111222", expiresAt: 42, qrPayload: "payload")
        let session = PairingSession(dto)
        XCTAssertEqual(session.code, "111222")
        XCTAssertEqual(session.qrPayload, "payload")
        XCTAssertEqual(session.expiresAt, 42)
    }
}
