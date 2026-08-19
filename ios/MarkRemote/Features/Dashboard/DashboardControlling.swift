import Foundation
import MarkRemoteModels

/// Snapshot of desktop status for the dashboard (no secrets / AI keys).
public struct DashboardSnapshot: Equatable, Sendable {
    public var online: Bool
    public var paired: Bool
    public var providerId: String?
    public var modelId: String?
    public var networkMode: String?
    public var runtimeStatus: String
    public var micActive: Bool
    public var activeTasks: Int
    public var pendingApprovals: Int

    public init(
        online: Bool,
        paired: Bool = false,
        providerId: String? = nil,
        modelId: String? = nil,
        networkMode: String? = nil,
        runtimeStatus: String = "неизвестно",
        micActive: Bool = false,
        activeTasks: Int = 0,
        pendingApprovals: Int = 0
    ) {
        self.online = online
        self.paired = paired
        self.providerId = providerId
        self.modelId = modelId
        self.networkMode = networkMode
        self.runtimeStatus = runtimeStatus
        self.micActive = micActive
        self.activeTasks = activeTasks
        self.pendingApprovals = pendingApprovals
    }

    public init(status: StatusResponse, runtimeStatus: String? = nil, micActive: Bool? = nil) {
        self.online = status.online
        self.paired = status.paired
        self.providerId = status.providerId
        self.modelId = status.modelId
        self.networkMode = status.networkMode
        self.runtimeStatus = runtimeStatus ?? status.assistantState ?? "ожидание"
        self.micActive = micActive ?? status.micActive ?? false
        self.activeTasks = status.activeTasks
        self.pendingApprovals = status.pendingApprovals
    }
}

public enum AssistantControlAction: String, Sendable, Equatable {
    case start
    case pause
    case stop
}

/// Injectable desktop runtime/session controller for start / pause / stop.
public protocol DashboardControlling: Sendable {
    func refreshStatus() async throws -> DashboardSnapshot
    func perform(_ action: AssistantControlAction) async throws
}
