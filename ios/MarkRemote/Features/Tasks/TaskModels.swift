import Foundation
import MarkRemoteModels

/// List-row summary mapped from Desktop API `TaskInfo`.
public struct TaskSummary: Identifiable, Equatable, Sendable {
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

    public init(dto: TaskInfo) {
        self.id = dto.id
        self.status = dto.status
        self.prompt = dto.prompt
        self.approvalRequired = dto.approvalRequired
    }

    public var statusTitleRU: String {
        TaskStatusLocalization.title(for: status)
    }
}

/// One step in a task plan shown on the detail screen.
public struct TaskPlanStep: Identifiable, Equatable, Sendable {
    public var id: String
    public var title: String
    public var status: String

    public init(id: String, title: String, status: String) {
        self.id = id
        self.title = title
        self.status = status
    }

    public var statusTitleRU: String {
        TaskStatusLocalization.title(for: status)
    }
}

/// Detail payload: summary + plan/steps.
public struct TaskDetail: Equatable, Sendable {
    public var summary: TaskSummary
    public var plan: [TaskPlanStep]
    public var currentStepIndex: Int?

    public init(
        summary: TaskSummary,
        plan: [TaskPlanStep] = [],
        currentStepIndex: Int? = nil
    ) {
        self.summary = summary
        self.plan = plan
        self.currentStepIndex = currentStepIndex
    }
}

public enum TaskStatusLocalization {
    public static func title(for status: String) -> String {
        switch status.lowercased() {
        case "queued", "pending": return "В очереди"
        case "running", "in_progress", "active": return "Выполняется"
        case "paused": return "На паузе"
        case "cancelled", "canceled": return "Отменена"
        case "failed", "error": return "Ошибка"
        case "completed", "done", "succeeded": return "Завершена"
        case "approval_required": return "Нужно подтверждение"
        default: return status
        }
    }
}
