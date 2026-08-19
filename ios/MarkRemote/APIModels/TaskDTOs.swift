import Foundation

/// POST `/v1/tasks`
public struct TaskCreateRequest: Codable, Sendable, Equatable {
    public var prompt: String
    public var idempotencyKey: String

    public init(prompt: String, idempotencyKey: String) {
        self.prompt = prompt
        self.idempotencyKey = idempotencyKey
    }
}

public struct TaskInfo: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var status: String
    public var prompt: String?
    public var approvalRequired: Bool

    public init(
        id: String,
        status: String,
        prompt: String? = nil,
        approvalRequired: Bool = false
    ) {
        self.id = id
        self.status = status
        self.prompt = prompt
        self.approvalRequired = approvalRequired
    }
}

/// GET `/v1/tasks`
public struct TaskListResponse: Codable, Sendable, Equatable {
    public var tasks: [TaskInfo]

    public init(tasks: [TaskInfo]) {
        self.tasks = tasks
    }
}

/// POST `/v1/tasks/{id}/cancel`
public struct TaskCancelRequest: Codable, Sendable, Equatable {
    public var idempotencyKey: String

    public init(idempotencyKey: String) {
        self.idempotencyKey = idempotencyKey
    }
}
