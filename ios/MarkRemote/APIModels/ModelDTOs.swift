import Foundation

public struct ModelInfo: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var providerId: String
    public var displayName: String?
    public var active: Bool

    public init(
        id: String,
        providerId: String,
        displayName: String? = nil,
        active: Bool = false
    ) {
        self.id = id
        self.providerId = providerId
        self.displayName = displayName
        self.active = active
    }
}

/// GET `/v1/models`
public struct ModelsListResponse: Codable, Sendable, Equatable {
    public var models: [ModelInfo]

    public init(models: [ModelInfo]) {
        self.models = models
    }
}

/// POST `/v1/models/activate`
public struct ModelsActivateRequest: Codable, Sendable, Equatable {
    public var modelId: String
    public var idempotencyKey: String
    public var role: String?

    public init(modelId: String, idempotencyKey: String, role: String? = nil) {
        self.modelId = modelId
        self.idempotencyKey = idempotencyKey
        self.role = role
    }
}
