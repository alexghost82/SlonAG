import Foundation

/// Single entry returned by an injectable files listing API.
public struct RemoteFileEntry: Identifiable, Sendable, Equatable {
    public var name: String
    public var path: String
    public var isDirectory: Bool

    public var id: String { path }

    public init(name: String, path: String, isDirectory: Bool) {
        self.name = name
        self.path = path
        self.isDirectory = isDirectory
    }
}

/// Result of listing a path that the desktop allowlist already approved.
public struct FilesListResult: Sendable, Equatable {
    public var path: String
    public var entries: [RemoteFileEntry]

    public init(path: String, entries: [RemoteFileEntry]) {
        self.path = path
        self.entries = entries
    }
}

/// Injectable files browser backend. Implementations must enforce allowlisting on the server.
public protocol FilesServing: Sendable {
    func listEntries(path: String) async throws -> FilesListResult
    func uploadFile(url: URL, directory: String) async throws
}

public enum FilesServiceError: Error, Sendable {
    case uploadUnavailable
}

public extension FilesServing {
    func uploadFile(url: URL, directory: String) async throws {
        throw FilesServiceError.uploadUnavailable
    }
}
