import Foundation

public struct SystemMetrics: Codable, Sendable, Equatable {
    public var cpuPercent: Double?
    public var memoryPercent: Double?
    public var networkMBps: Double?
    public var gpuPercent: Double?
    public var temperatureCelsius: Double?
    public var uptimeSeconds: Double?
    public var processCount: Int?
    public var osName: String?

    public init(
        cpuPercent: Double? = nil,
        memoryPercent: Double? = nil,
        networkMBps: Double? = nil,
        gpuPercent: Double? = nil,
        temperatureCelsius: Double? = nil,
        uptimeSeconds: Double? = nil,
        processCount: Int? = nil,
        osName: String? = nil
    ) {
        self.cpuPercent = cpuPercent
        self.memoryPercent = memoryPercent
        self.networkMBps = networkMBps
        self.gpuPercent = gpuPercent
        self.temperatureCelsius = temperatureCelsius
        self.uptimeSeconds = uptimeSeconds
        self.processCount = processCount
        self.osName = osName
    }
}

/// GET `/v1/status` — desktop health without secrets.
public struct StatusResponse: Codable, Sendable, Equatable {
    public var online: Bool
    public var paired: Bool
    public var providerId: String?
    public var modelId: String?
    public var networkMode: String?
    public var privacyProfile: String?
    public var activeTasks: Int
    public var pendingApprovals: Int
    public var assistantState: String?
    public var micActive: Bool?
    public var localTTSAvailable: Bool?
    public var localSTTAvailable: Bool?
    public var desktopAPIActive: Bool?
    public var systemMetrics: SystemMetrics?

    public init(
        online: Bool,
        paired: Bool,
        providerId: String? = nil,
        modelId: String? = nil,
        networkMode: String? = nil,
        privacyProfile: String? = nil,
        activeTasks: Int = 0,
        pendingApprovals: Int = 0,
        assistantState: String? = nil,
        micActive: Bool? = nil,
        localTTSAvailable: Bool? = nil,
        localSTTAvailable: Bool? = nil,
        desktopAPIActive: Bool? = nil,
        systemMetrics: SystemMetrics? = nil
    ) {
        self.online = online
        self.paired = paired
        self.providerId = providerId
        self.modelId = modelId
        self.networkMode = networkMode
        self.privacyProfile = privacyProfile
        self.activeTasks = activeTasks
        self.pendingApprovals = pendingApprovals
        self.assistantState = assistantState
        self.micActive = micActive
        self.localTTSAvailable = localTTSAvailable
        self.localSTTAvailable = localSTTAvailable
        self.desktopAPIActive = desktopAPIActive
        self.systemMetrics = systemMetrics
    }
}
