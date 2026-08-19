import Foundation
import MarkRemoteModels
import MarkRemoteNetworking

/// Injectable Desktop API surface for Approvals.
public protocol ApprovalsClienting: Sendable {
    func listApprovals() async throws -> [ApprovalItem]
    func decide(
        id: String,
        decision: ApprovalDecisionKind,
        idempotencyKey: String
    ) async throws -> ApprovalItem
}

public final class DesktopAPIApprovalsClient: ApprovalsClienting, @unchecked Sendable {
    private let api: DesktopAPIClient

    public init(api: DesktopAPIClient) {
        self.api = api
    }

    public func listApprovals() async throws -> [ApprovalItem] {
        let response = try await api.listApprovals()
        return response.approvals.map { ApprovalItem(dto: $0) }
    }

    public func decide(
        id: String,
        decision: ApprovalDecisionKind,
        idempotencyKey: String
    ) async throws -> ApprovalItem {
        let updated = try await api.decideApproval(
            id: id,
            body: ApprovalDecisionRequest(
                decision: decision.rawValue,
                idempotencyKey: idempotencyKey
            )
        )
        return ApprovalItem(dto: updated)
    }
}

public enum ApprovalsClientError: Error, Sendable, Equatable {
    case notFound(String)
}
