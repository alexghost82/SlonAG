import Combine
import Foundation
import MarkRemoteSecurity

@MainActor
public final class ApprovalsViewModel: ObservableObject {
    @Published public private(set) var items: [ApprovalItem] = []
    @Published public private(set) var selected: ApprovalItem?
    @Published public private(set) var isLoading = false
    @Published public private(set) var isDeciding = false
    @Published public private(set) var errorMessage: String?
    /// Set when allow is blocked (biometric failure / cancel / unavailable). Never auto-approves.
    @Published public private(set) var blockedReason: String?
    @Published public private(set) var lastSubmittedDecision: ApprovalDecisionKind?

    private let client: any ApprovalsClienting
    private let biometrics: any BiometricAuthenticating
    private let makeIdempotencyKey: () -> String

    public init(
        client: any ApprovalsClienting,
        biometrics: any BiometricAuthenticating,
        makeIdempotencyKey: @escaping () -> String = { UUID().uuidString }
    ) {
        self.client = client
        self.biometrics = biometrics
        self.makeIdempotencyKey = makeIdempotencyKey
    }

    public func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            items = try await client.listApprovals()
            if let selected, let refreshed = items.first(where: { $0.id == selected.id }) {
                self.selected = refreshed
            } else if selected == nil {
                self.selected = items.first(where: \.isPending) ?? items.first
            }
        } catch {
            errorMessage = ApprovalsStrings.loadFailed
        }
    }

    public func select(_ item: ApprovalItem) {
        selected = item
        blockedReason = nil
        errorMessage = nil
    }

    /// Allow-once. Risk ≥ 3 requires successful biometric evaluation first.
    public func allowOnce(id: String? = nil) async {
        guard let item = resolveItem(id: id) else {
            errorMessage = ApprovalsStrings.missingApproval
            return
        }
        blockedReason = nil
        lastSubmittedDecision = nil

        if item.requiresBiometricForAllow {
            let authorized = await evaluateBiometricGate()
            guard authorized else { return }
        }

        await submit(decision: .allowOnce, for: item)
    }

    public func deny(id: String? = nil) async {
        guard let item = resolveItem(id: id) else {
            errorMessage = ApprovalsStrings.missingApproval
            return
        }
        blockedReason = nil
        lastSubmittedDecision = nil
        await submit(decision: .deny, for: item)
    }

    private func resolveItem(id: String?) -> ApprovalItem? {
        if let id {
            return items.first(where: { $0.id == id }) ?? (selected?.id == id ? selected : nil)
        }
        return selected
    }

    private func evaluateBiometricGate() async -> Bool {
        guard biometrics.canEvaluate() else {
            blockedReason = ApprovalsStrings.biometricUnavailable
            return false
        }
        do {
            let success = try await biometrics.evaluate(reason: ApprovalsStrings.biometricReason)
            if !success {
                blockedReason = ApprovalsStrings.biometricFailed
            }
            return success
        } catch BiometricAuthError.cancelled {
            blockedReason = ApprovalsStrings.biometricCancelled
            return false
        } catch BiometricAuthError.unavailable {
            blockedReason = ApprovalsStrings.biometricUnavailable
            return false
        } catch {
            blockedReason = ApprovalsStrings.biometricFailed
            return false
        }
    }

    private func submit(decision: ApprovalDecisionKind, for item: ApprovalItem) async {
        isDeciding = true
        errorMessage = nil
        defer { isDeciding = false }
        do {
            let updated = try await client.decide(
                id: item.id,
                decision: decision,
                idempotencyKey: makeIdempotencyKey()
            )
            lastSubmittedDecision = decision
            if let index = items.firstIndex(where: { $0.id == updated.id }) {
                items[index] = updated
            }
            selected = updated
        } catch {
            errorMessage = ApprovalsStrings.decisionFailed
        }
    }
}

public enum ApprovalsStrings {
    public static let title = "Подтверждения"
    public static let actionLabel = "Действие"
    public static let riskLabel = "Уровень риска"
    public static let sourceLabel = "Источник"
    public static let argumentsLabel = "Точные аргументы"
    public static let pathLabel = "Путь"
    public static let urlLabel = "URL"
    public static let intentLabel = "Намерение"
    public static let statusLabel = "Статус"
    public static let allowOnce = "Разрешить один раз"
    public static let deny = "Отклонить"
    public static let narrowRule = "Узкое правило (необязательно)"
    public static let emptyTitle = "Нет подтверждений"
    public static let emptyMessage = "Когда агенту понадобится разрешение, запрос появится здесь."
    public static let loadFailed = "Не удалось загрузить подтверждения."
    public static let decisionFailed = "Не удалось отправить решение."
    public static let missingApproval = "Подтверждение не выбрано."
    public static let biometricReason = "Подтвердите действие с высоким уровнем риска"
    public static let biometricFailed = "Биометрическая проверка не пройдена. Разрешение не отправлено."
    public static let biometricCancelled = "Биометрия отменена. Разрешение не отправлено."
    public static let biometricUnavailable = "Биометрия недоступна. Разрешение не отправлено."
    public static let pendingOnlyHint = "Разрешение никогда не выдаётся автоматически."
}
