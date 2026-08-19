import Foundation
import MarkRemoteModels
import Observation

@MainActor
@Observable
public final class MemoryViewModel {
    public private(set) var entries: [MemoryEntry] = []
    public private(set) var isLoading = false
    public private(set) var errorMessage: String?
    public private(set) var pendingDeleteId: String?
    public private(set) var lastDeleteIdempotencyKey: String?

    private let service: any MemoryServing

    public init(service: any MemoryServing) {
        self.service = service
    }

    public var isConfirmingDelete: Bool {
        pendingDeleteId != nil
    }

    public func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            entries = try await service.listEntries()
        } catch {
            errorMessage = "Не удалось загрузить память: \(error.localizedDescription)"
        }
    }

    /// Stages a delete; nothing is removed until `confirmDelete()`.
    public func requestDelete(id: String) {
        pendingDeleteId = id
    }

    public func cancelDelete() {
        pendingDeleteId = nil
    }

    public func confirmDelete() async {
        guard let id = pendingDeleteId else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        let key = IdempotencyKey.make()
        lastDeleteIdempotencyKey = key
        do {
            try await service.deleteEntry(id: id, idempotencyKey: key)
            entries.removeAll { $0.id == id }
            pendingDeleteId = nil
        } catch {
            errorMessage = "Не удалось удалить запись: \(error.localizedDescription)"
        }
    }

    public func clearAllConfirmed() async {
        let ids = entries.map(\.id)
        for id in ids {
            pendingDeleteId = id
            await confirmDelete()
            if errorMessage != nil { break }
        }
    }
}
