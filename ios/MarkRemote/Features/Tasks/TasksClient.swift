import Foundation
import MarkRemoteModels
import MarkRemoteNetworking

/// Injectable Desktop API surface for Tasks (list/create/detail + pause/cancel/retry).
public protocol TasksClienting: Sendable {
    func listTasks() async throws -> [TaskSummary]
    func createTask(prompt: String, idempotencyKey: String) async throws -> TaskSummary
    func taskDetail(id: String) async throws -> TaskDetail
    func pauseTask(id: String, idempotencyKey: String) async throws -> TaskSummary
    func cancelTask(id: String, idempotencyKey: String) async throws -> TaskSummary
    func retryTask(id: String, idempotencyKey: String) async throws -> TaskSummary
}

/// Adapts `DesktopAPIClient` to `TasksClienting`.
/// Pause/retry are local status hooks until dedicated Desktop routes exist; cancel uses `/v1/tasks/{id}/cancel`.
public final class DesktopAPITasksClient: TasksClienting, @unchecked Sendable {
    private let api: DesktopAPIClient
    private let details: LockIsolated<[String: TaskDetail]>

    public init(api: DesktopAPIClient) {
        self.api = api
        self.details = LockIsolated([:])
    }

    public func listTasks() async throws -> [TaskSummary] {
        let response = try await api.listTasks()
        return response.tasks.map(TaskSummary.init(dto:))
    }

    public func createTask(prompt: String, idempotencyKey: String) async throws -> TaskSummary {
        let info = try await api.createTask(
            TaskCreateRequest(prompt: prompt, idempotencyKey: idempotencyKey)
        )
        let summary = TaskSummary(dto: info)
        details.withLock { store in
            store[summary.id] = TaskDetail(
                summary: summary,
                plan: [
                    TaskPlanStep(id: "\(summary.id)-step-1", title: "Планирование", status: "queued"),
                    TaskPlanStep(id: "\(summary.id)-step-2", title: "Выполнение", status: "queued"),
                ],
                currentStepIndex: 0
            )
        }
        return summary
    }

    public func taskDetail(id: String) async throws -> TaskDetail {
        if let cached = details.withLock({ $0[id] }) {
            return cached
        }
        let listed = try await listTasks()
        guard let summary = listed.first(where: { $0.id == id }) else {
            throw TasksClientError.notFound(id)
        }
        let detail = TaskDetail(
            summary: summary,
            plan: [
                TaskPlanStep(id: "\(id)-step-1", title: "Планирование", status: summary.status),
            ],
            currentStepIndex: 0
        )
        details.withLock { $0[id] = detail }
        return detail
    }

    public func pauseTask(id: String, idempotencyKey: String) async throws -> TaskSummary {
        _ = idempotencyKey
        return try await mutateLocalStatus(id: id, status: "paused")
    }

    public func cancelTask(id: String, idempotencyKey: String) async throws -> TaskSummary {
        let info = try await api.cancelTask(
            id: id,
            body: TaskCancelRequest(idempotencyKey: idempotencyKey)
        )
        let summary = TaskSummary(dto: info)
        details.withLock { store in
            if var detail = store[id] {
                detail.summary = summary
                store[id] = detail
            }
        }
        return summary
    }

    public func retryTask(id: String, idempotencyKey: String) async throws -> TaskSummary {
        _ = idempotencyKey
        return try await mutateLocalStatus(id: id, status: "queued")
    }

    private func mutateLocalStatus(id: String, status: String) async throws -> TaskSummary {
        let detail = try await taskDetail(id: id)
        var updated = detail
        updated.summary.status = status
        details.withLock { $0[id] = updated }
        return updated.summary
    }
}

public enum TasksClientError: Error, Sendable, Equatable {
    case notFound(String)
}

/// Tiny mutex for in-memory detail cache.
private final class LockIsolated<Value>: @unchecked Sendable {
    private var value: Value
    private let lock = NSLock()

    init(_ value: Value) {
        self.value = value
    }

    func withLock<R>(_ body: (inout Value) throws -> R) rethrows -> R {
        lock.lock()
        defer { lock.unlock() }
        return try body(&value)
    }
}
