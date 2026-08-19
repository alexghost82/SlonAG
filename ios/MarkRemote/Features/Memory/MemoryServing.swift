import Foundation
import MarkRemoteModels

/// Injectable memory list / delete client.
public protocol MemoryServing: Sendable {
    func listEntries() async throws -> [MemoryEntry]
    func deleteEntry(id: String, idempotencyKey: String) async throws
}
