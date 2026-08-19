import Foundation

public enum CredentialStoreError: Error, Sendable, Equatable {
    case notFound
    case encodingFailed
    case decodingFailed
    case underlying(String)
}

/// Injectable storage for device credentials (Keychain in production, memory in tests).
public protocol CredentialStore: Sendable {
    func save(_ credentials: DeviceCredentials) throws
    func load() throws -> DeviceCredentials?
    func delete() throws
}

/// In-memory store for unit tests. Never prints secret material.
public final class InMemoryCredentialStore: CredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var stored: DeviceCredentials?

    public init(initial: DeviceCredentials? = nil) {
        self.stored = initial
    }

    public func save(_ credentials: DeviceCredentials) throws {
        lock.lock()
        defer { lock.unlock() }
        stored = credentials
    }

    public func load() throws -> DeviceCredentials? {
        lock.lock()
        defer { lock.unlock() }
        return stored
    }

    public func delete() throws {
        lock.lock()
        defer { lock.unlock() }
        stored = nil
    }
}
