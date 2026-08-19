import Foundation
import MarkRemoteModels

/// Injectable client for model list / activate. No AI API keys are involved.
public protocol ModelsServing: Sendable {
    func listModels() async throws -> [ModelInfo]
    func activateModel(modelId: String, idempotencyKey: String, role: String?) async throws -> ModelInfo
}

extension ModelsServing {
    public func activateModel(modelId: String, idempotencyKey: String) async throws -> ModelInfo {
        try await activateModel(modelId: modelId, idempotencyKey: idempotencyKey, role: nil)
    }
}
