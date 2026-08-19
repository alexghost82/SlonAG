import Combine
import Foundation

@MainActor
public final class TasksListViewModel: ObservableObject {
    @Published public private(set) var tasks: [TaskSummary] = []
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?
    @Published public var draftPrompt: String = ""

    private let client: any TasksClienting
    private let makeIdempotencyKey: () -> String

    public init(
        client: any TasksClienting,
        makeIdempotencyKey: @escaping () -> String = { UUID().uuidString }
    ) {
        self.client = client
        self.makeIdempotencyKey = makeIdempotencyKey
    }

    public func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            tasks = try await client.listTasks()
        } catch {
            errorMessage = TasksStrings.loadFailed
        }
    }

    public func createFromDraft() async {
        let prompt = draftPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else {
            errorMessage = TasksStrings.emptyPrompt
            return
        }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let created = try await client.createTask(
                prompt: prompt,
                idempotencyKey: makeIdempotencyKey()
            )
            draftPrompt = ""
            if let index = tasks.firstIndex(where: { $0.id == created.id }) {
                tasks[index] = created
            } else {
                tasks.insert(created, at: 0)
            }
        } catch {
            errorMessage = TasksStrings.createFailed
        }
    }
}

@MainActor
public final class TaskDetailViewModel: ObservableObject {
    @Published public private(set) var detail: TaskDetail?
    @Published public private(set) var isLoading = false
    @Published public private(set) var isActing = false
    @Published public private(set) var errorMessage: String?

    public let taskID: String
    private let client: any TasksClienting
    private let makeIdempotencyKey: () -> String

    public init(
        taskID: String,
        client: any TasksClienting,
        makeIdempotencyKey: @escaping () -> String = { UUID().uuidString }
    ) {
        self.taskID = taskID
        self.client = client
        self.makeIdempotencyKey = makeIdempotencyKey
    }

    public func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            detail = try await client.taskDetail(id: taskID)
        } catch {
            errorMessage = TasksStrings.loadFailed
        }
    }

    public func pause() async {
        await performAction { client, key in
            try await client.pauseTask(id: taskID, idempotencyKey: key)
        }
    }

    public func cancel() async {
        await performAction { client, key in
            try await client.cancelTask(id: taskID, idempotencyKey: key)
        }
    }

    public func retry() async {
        await performAction { client, key in
            try await client.retryTask(id: taskID, idempotencyKey: key)
        }
    }

    private func performAction(
        _ body: (any TasksClienting, String) async throws -> TaskSummary
    ) async {
        isActing = true
        errorMessage = nil
        defer { isActing = false }
        do {
            let summary = try await body(client, makeIdempotencyKey())
            if var current = detail {
                current.summary = summary
                detail = current
            } else {
                detail = TaskDetail(summary: summary)
            }
        } catch {
            errorMessage = TasksStrings.actionFailed
        }
    }
}

public enum TasksStrings {
    public static let listTitle = "Задачи"
    public static let detailTitle = "Детали задачи"
    public static let planSection = "План"
    public static let promptLabel = "Запрос"
    public static let statusLabel = "Статус"
    public static let createButton = "Создать задачу"
    public static let pauseButton = "Пауза"
    public static let cancelButton = "Отменить"
    public static let retryButton = "Повторить"
    public static let emptyTitle = "Нет задач"
    public static let emptyMessage = "Создайте задачу, чтобы увидеть план и шаги."
    public static let loadFailed = "Не удалось загрузить задачи."
    public static let createFailed = "Не удалось создать задачу."
    public static let actionFailed = "Не удалось выполнить действие."
    public static let emptyPrompt = "Введите текст запроса."
    public static let approvalRequired = "Требуется подтверждение"
}
