import Foundation

public struct MemoryEntry: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var kind: String
    public var summary: String?

    public init(id: String, kind: String, summary: String? = nil) {
        self.id = id
        self.kind = kind
        self.summary = summary
    }
}

/// GET `/v1/memory`
public struct MemoryGetResponse: Codable, Sendable, Equatable {
    public var entries: [MemoryEntry]

    public init(entries: [MemoryEntry]) {
        self.entries = entries
    }
}

/// DELETE `/v1/memory/{id}` body
public struct MemoryDeleteRequest: Codable, Sendable, Equatable {
    public var idempotencyKey: String

    public init(idempotencyKey: String) {
        self.idempotencyKey = idempotencyKey
    }
}
