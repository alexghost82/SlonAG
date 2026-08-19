import Foundation
import MarkRemoteModels
import Observation

@MainActor
@Observable
public final class ModelsViewModel {
    public private(set) var models: [ModelInfo] = []
    public private(set) var isLoading = false
    public private(set) var errorMessage: String?
    public private(set) var lastActivationIdempotencyKey: String?

    private let service: any ModelsServing

    public init(service: any ModelsServing) {
        self.service = service
    }

    public var activeModel: ModelInfo? {
        models.first(where: \.active)
    }

    public func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            models = try await service.listModels()
        } catch {
            errorMessage = Self.russianError(error)
        }
    }

    public func activate(modelId: String, role: String? = nil) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        let key = IdempotencyKey.make()
        lastActivationIdempotencyKey = key
        do {
            let updated = try await service.activateModel(
                modelId: modelId,
                idempotencyKey: key,
                role: role
            )
            var next = models.map { model -> ModelInfo in
                var copy = model
                copy.active = (model.id == updated.id)
                return copy
            }
            if let index = next.firstIndex(where: { $0.id == updated.id }) {
                next[index] = updated
            } else {
                next.append(updated)
            }
            models = next
        } catch {
            errorMessage = Self.russianError(error)
        }
    }

    private static func russianError(_ error: Error) -> String {
        "Не удалось обновить список моделей: \(error.localizedDescription)"
    }
}
