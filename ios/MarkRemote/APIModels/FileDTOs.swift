import Foundation

public struct FileEntryDTO: Codable, Sendable, Equatable {
    public var name: String
    public var path: String
    public var isDirectory: Bool

    public init(name: String, path: String, isDirectory: Bool) {
        self.name = name
        self.path = path
        self.isDirectory = isDirectory
    }
}

public struct FilesListResponse: Codable, Sendable, Equatable {
    public var path: String
    public var entries: [FileEntryDTO]

    public init(path: String, entries: [FileEntryDTO]) {
        self.path = path
        self.entries = entries
    }
}

public struct FileUploadRequest: Codable, Sendable, Equatable {
    public var directory: String
    public var filename: String
    public var contentBase64: String
    public var idempotencyKey: String

    public init(
        directory: String,
        filename: String,
        contentBase64: String,
        idempotencyKey: String
    ) {
        self.directory = directory
        self.filename = filename
        self.contentBase64 = contentBase64
        self.idempotencyKey = idempotencyKey
    }
}

public struct FileUploadResponse: Codable, Sendable, Equatable {
    public var entry: FileEntryDTO

    public init(entry: FileEntryDTO) {
        self.entry = entry
    }
}
