import XCTest
@testable import MarkRemoteFeatures

// MARK: - Mocks

private final class MockTasksClient: TasksClienting, @unchecked Sendable {
    var tasks: [TaskSummary]
    var details: [String: TaskDetail]
    private(set) var pauseCalls: [String] = []
    private(set) var cancelCalls: [String] = []
    private(set) var retryCalls: [String] = []
    private(set) var createCalls: [(String, String)] = []

    init(tasks: [TaskSummary] = [], details: [String: TaskDetail] = [:]) {
        self.tasks = tasks
        self.details = details
    }

    func listTasks() async throws -> [TaskSummary] {
        tasks
    }

    func createTask(prompt: String, idempotencyKey: String) async throws -> TaskSummary {
        createCalls.append((prompt, idempotencyKey))
        let summary = TaskSummary(
            id: "task-\(tasks.count + 1)",
            status: "queued",
            prompt: prompt,
            approvalRequired: true
        )
        tasks.insert(summary, at: 0)
        details[summary.id] = TaskDetail(
            summary: summary,
            plan: [
                TaskPlanStep(id: "s1", title: "Планирование", status: "queued"),
                TaskPlanStep(id: "s2", title: "Выполнение", status: "queued"),
            ],
            currentStepIndex: 0
        )
        return summary
    }

    func taskDetail(id: String) async throws -> TaskDetail {
        if let detail = details[id] {
            return detail
        }
        guard let summary = tasks.first(where: { $0.id == id }) else {
            throw TasksClientError.notFound(id)
        }
        return TaskDetail(summary: summary)
    }

    func pauseTask(id: String, idempotencyKey: String) async throws -> TaskSummary {
        _ = idempotencyKey
        pauseCalls.append(id)
        return mutate(id: id, status: "paused")
    }

    func cancelTask(id: String, idempotencyKey: String) async throws -> TaskSummary {
        _ = idempotencyKey
        cancelCalls.append(id)
        return mutate(id: id, status: "cancelled")
    }

    func retryTask(id: String, idempotencyKey: String) async throws -> TaskSummary {
        _ = idempotencyKey
        retryCalls.append(id)
        return mutate(id: id, status: "queued")
    }

    private func mutate(id: String, status: String) -> TaskSummary {
        guard let index = tasks.firstIndex(where: { $0.id == id }) else {
            return TaskSummary(id: id, status: status)
        }
        tasks[index].status = status
        if var detail = details[id] {
            detail.summary = tasks[index]
            details[id] = detail
        }
        return tasks[index]
    }
}

private final class MockApprovalsClient: ApprovalsClienting, @unchecked Sendable {
    var items: [ApprovalItem]
    private(set) var decisions: [(String, ApprovalDecisionKind, String)] = []

    init(items: [ApprovalItem] = []) {
        self.items = items
    }

    func listApprovals() async throws -> [ApprovalItem] {
        items
    }

    func decide(
        id: String,
        decision: ApprovalDecisionKind,
        idempotencyKey: String
    ) async throws -> ApprovalItem {
        decisions.append((id, decision, idempotencyKey))
        guard let index = items.firstIndex(where: { $0.id == id }) else {
            throw ApprovalsClientError.notFound(id)
        }
        items[index].status = decision == .allowOnce ? "approved" : "denied"
        return items[index]
    }
}

// MARK: - Tests

final class TasksApprovalsTests: XCTestCase {
    func testTasksListAndCreateViaInjectableClient() async {
        let client = MockTasksClient()
        let listVM = await TasksListViewModel(
            client: client,
            makeIdempotencyKey: { "idem-create" }
        )
        await listVM.load()
        let emptyCount = await listVM.tasks.count
        XCTAssertEqual(emptyCount, 0)

        await MainActor.run { listVM.draftPrompt = "Собери отчёт" }
        await listVM.createFromDraft()

        let tasks = await listVM.tasks
        XCTAssertEqual(tasks.count, 1)
        XCTAssertEqual(tasks[0].prompt, "Собери отчёт")
        XCTAssertEqual(client.createCalls.count, 1)
        XCTAssertEqual(client.createCalls[0].1, "idem-create")
    }

    func testTaskDetailPauseCancelRetryHooks() async throws {
        let summary = TaskSummary(id: "t1", status: "running", prompt: "Шаги", approvalRequired: false)
        let client = MockTasksClient(
            tasks: [summary],
            details: [
                "t1": TaskDetail(
                    summary: summary,
                    plan: [
                        TaskPlanStep(id: "a", title: "Шаг 1", status: "running"),
                        TaskPlanStep(id: "b", title: "Шаг 2", status: "queued"),
                    ],
                    currentStepIndex: 0
                ),
            ]
        )
        let detailVM = await TaskDetailViewModel(
            taskID: "t1",
            client: client,
            makeIdempotencyKey: { "idem-action" }
        )
        await detailVM.load()
        let planCount = await detailVM.detail?.plan.count
        XCTAssertEqual(planCount, 2)

        await detailVM.pause()
        XCTAssertEqual(client.pauseCalls, ["t1"])
        let paused = await detailVM.detail?.summary.status
        XCTAssertEqual(paused, "paused")

        await detailVM.retry()
        XCTAssertEqual(client.retryCalls, ["t1"])
        let retried = await detailVM.detail?.summary.status
        XCTAssertEqual(retried, "queued")

        await detailVM.cancel()
        XCTAssertEqual(client.cancelCalls, ["t1"])
        let cancelled = await detailVM.detail?.summary.status
        XCTAssertEqual(cancelled, "cancelled")
    }

    func testApprovalRiskParsingAndRussianTitles() {
        XCTAssertEqual(ApprovalRisk.level(from: "3"), 3)
        XCTAssertEqual(ApprovalRisk.level(from: "biometric"), 4)
        XCTAssertEqual(ApprovalRisk.level(from: "high"), 3)
        XCTAssertEqual(ApprovalRisk.titleRU(for: 3), "3 — точное подтверждение")
        XCTAssertEqual(ApprovalsStrings.allowOnce, "Разрешить один раз")
        XCTAssertEqual(TasksStrings.pauseButton, "Пауза")
    }

    func testApprovalsViewModelShowsFullPathURLAndArgs() async {
        let item = ApprovalItem(
            id: "a1",
            action: "file_controller.delete",
            riskRaw: "2",
            status: "pending",
            source: "user",
            exactArguments: #"{"action":"delete","path":"/Users/slon/secret.txt"}"#,
            path: "/Users/slon/secret.txt",
            url: "https://example.com/callback"
        )
        let client = MockApprovalsClient(items: [item])
        let biometrics = MockBiometricAuthenticator(result: .success(true))
        let vm = await ApprovalsViewModel(client: client, biometrics: biometrics)
        await vm.load()

        let selected = await vm.selected
        XCTAssertEqual(selected?.exactArguments, item.exactArguments)
        XCTAssertEqual(selected?.path, "/Users/slon/secret.txt")
        XCTAssertEqual(selected?.url, "https://example.com/callback")
        XCTAssertEqual(selected?.source, "user")
        XCTAssertEqual(selected?.action, "file_controller.delete")
    }

    func testAllowOnceLowRiskDoesNotRequireBiometric() async {
        let item = ApprovalItem(
            id: "a-low",
            action: "status.read",
            riskRaw: "1",
            status: "pending",
            source: "user"
        )
        let client = MockApprovalsClient(items: [item])
        let biometrics = MockBiometricAuthenticator(result: .success(true))
        let vm = await ApprovalsViewModel(
            client: client,
            biometrics: biometrics,
            makeIdempotencyKey: { "idem-allow" }
        )
        await vm.load()
        await vm.allowOnce()

        XCTAssertEqual(biometrics.evaluateCallCount, 0)
        XCTAssertEqual(client.decisions.count, 1)
        XCTAssertEqual(client.decisions[0].1, .allowOnce)
        let decision = await vm.lastSubmittedDecision
        XCTAssertEqual(decision, .allowOnce)
        let blocked = await vm.blockedReason
        XCTAssertNil(blocked)
    }

    func testAllowOnceHighRiskFailsWhenBiometricFails() async {
        let item = ApprovalItem(
            id: "a-high",
            action: "shell.run",
            riskRaw: "3",
            status: "pending",
            source: "tool_result",
            exactArguments: #"{"cmd":"rm -rf /"}"#,
            path: "/tmp/danger"
        )
        let client = MockApprovalsClient(items: [item])
        let biometrics = MockBiometricAuthenticator(result: .failure(.failed))
        let vm = await ApprovalsViewModel(client: client, biometrics: biometrics)
        await vm.load()
        await vm.allowOnce()

        XCTAssertEqual(biometrics.evaluateCallCount, 1)
        XCTAssertEqual(client.decisions.count, 0, "Must not auto-approve or send allow on biometric failure")
        let blocked = await vm.blockedReason
        XCTAssertEqual(blocked, ApprovalsStrings.biometricFailed)
        let decision = await vm.lastSubmittedDecision
        XCTAssertNil(decision)
        let status = await vm.selected?.status
        XCTAssertEqual(status, "pending")
    }

    func testAllowOnceHighRiskFailsWhenBiometricReturnsFalse() async {
        let item = ApprovalItem(
            id: "a-high-false",
            action: "keys.export",
            riskRaw: "4",
            status: "pending"
        )
        let client = MockApprovalsClient(items: [item])
        let biometrics = MockBiometricAuthenticator(result: .success(false))
        let vm = await ApprovalsViewModel(client: client, biometrics: biometrics)
        await vm.load()
        await vm.allowOnce()

        XCTAssertEqual(biometrics.evaluateCallCount, 1)
        XCTAssertTrue(client.decisions.isEmpty)
        let blocked = await vm.blockedReason
        XCTAssertEqual(blocked, ApprovalsStrings.biometricFailed)
    }

    func testAllowOnceHighRiskSucceedsAfterBiometric() async {
        let item = ApprovalItem(
            id: "a-ok",
            action: "install.package",
            riskRaw: "3",
            status: "pending",
            path: "/Applications/Mark.app",
            url: "https://example.local/pkg"
        )
        let client = MockApprovalsClient(items: [item])
        let biometrics = MockBiometricAuthenticator(result: .success(true))
        let vm = await ApprovalsViewModel(
            client: client,
            biometrics: biometrics,
            makeIdempotencyKey: { "idem-bio-ok" }
        )
        await vm.load()
        await vm.allowOnce()

        XCTAssertEqual(biometrics.evaluateCallCount, 1)
        XCTAssertEqual(biometrics.lastReason, ApprovalsStrings.biometricReason)
        XCTAssertEqual(client.decisions.count, 1)
        XCTAssertEqual(client.decisions[0].0, "a-ok")
        XCTAssertEqual(client.decisions[0].1, .allowOnce)
        let decision = await vm.lastSubmittedDecision
        XCTAssertEqual(decision, .allowOnce)
        let status = await vm.selected?.status
        XCTAssertEqual(status, "approved")
        let blocked = await vm.blockedReason
        XCTAssertNil(blocked)
    }

    func testDenyDoesNotRequireBiometricEvenForHighRisk() async {
        let item = ApprovalItem(
            id: "a-deny",
            action: "shutdown",
            riskRaw: "4",
            status: "pending"
        )
        let client = MockApprovalsClient(items: [item])
        let biometrics = MockBiometricAuthenticator(result: .failure(.failed))
        let vm = await ApprovalsViewModel(client: client, biometrics: biometrics)
        await vm.load()
        await vm.deny()

        XCTAssertEqual(biometrics.evaluateCallCount, 0)
        XCTAssertEqual(client.decisions.count, 1)
        XCTAssertEqual(client.decisions[0].1, .deny)
        let status = await vm.selected?.status
        XCTAssertEqual(status, "denied")
    }

    func testNeverAutoApprovesOnLoad() async {
        let item = ApprovalItem(
            id: "a-pending",
            action: "desktop.click",
            riskRaw: "2",
            status: "pending"
        )
        let client = MockApprovalsClient(items: [item])
        let biometrics = MockBiometricAuthenticator(result: .success(true))
        let vm = await ApprovalsViewModel(client: client, biometrics: biometrics)
        await vm.load()

        XCTAssertTrue(client.decisions.isEmpty)
        let status = await vm.selected?.status
        XCTAssertEqual(status, "pending")
        let decision = await vm.lastSubmittedDecision
        XCTAssertNil(decision)
    }
}
