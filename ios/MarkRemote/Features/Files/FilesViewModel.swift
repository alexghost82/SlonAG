import Foundation
import Observation

@MainActor
@Observable
public final class FilesViewModel {
    /// User-visible notice: browsing never escapes the desktop allowlist.
    public static let allowlistNoticeRU =
        "Доступны только пути из разрешённого списка на компьютере. Произвольный ввод вне списка недоступен."

    public private(set) var currentPath: String
    public private(set) var entries: [RemoteFileEntry] = []
    public private(set) var isLoading = false
    public private(set) var errorMessage: String?
    public private(set) var pathHistory: [String]

    private let service: any FilesServing
    private let rootPath: String

    public init(service: any FilesServing, rootPath: String = "/") {
        self.service = service
        self.rootPath = rootPath
        self.currentPath = rootPath
        self.pathHistory = [rootPath]
    }

    public var allowlistNotice: String { Self.allowlistNoticeRU }

    public var canGoUp: Bool {
        pathHistory.count > 1
    }

    public func load() async {
        await list(path: currentPath, pushHistory: false)
    }

    public func open(_ entry: RemoteFileEntry) async {
        guard entry.isDirectory else { return }
        await list(path: entry.path, pushHistory: true)
    }

    public func goUp() async {
        guard canGoUp else { return }
        pathHistory.removeLast()
        let previous = pathHistory.last ?? rootPath
        await list(path: previous, pushHistory: false)
    }

    public func upload(_ url: URL) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await service.uploadFile(url: url, directory: currentPath)
            await list(path: currentPath, pushHistory: false)
        } catch {
            errorMessage = "Не удалось загрузить файл: \(error.localizedDescription)"
        }
    }

    /// Free-form path navigation is intentionally unsupported — only listed entries or history.
    public var supportsArbitraryPathEntry: Bool { false }

    private func list(path: String, pushHistory: Bool) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let result = try await service.listEntries(path: path)
            currentPath = result.path
            entries = result.entries
            if pushHistory, pathHistory.last != result.path {
                pathHistory.append(result.path)
            }
        } catch {
            errorMessage = "Не удалось получить список файлов: \(error.localizedDescription)"
        }
    }
}
