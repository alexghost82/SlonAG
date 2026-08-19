@preconcurrency import Appwrite
import Foundation
import Observation

public struct AppwriteConfiguration: Sendable, Equatable {
    public var endpoint: String
    public var projectId: String
    public var databaseId: String
    public var settingsTableId: String

    public var isConfigured: Bool {
        !endpoint.isEmpty && !projectId.isEmpty && !databaseId.isEmpty && !settingsTableId.isEmpty
    }

    public init(
        endpoint: String,
        projectId: String,
        databaseId: String,
        settingsTableId: String
    ) {
        self.endpoint = endpoint
        self.projectId = projectId
        self.databaseId = databaseId
        self.settingsTableId = settingsTableId
    }

    public static func fromBundle(_ bundle: Bundle = .main) -> Self {
        func value(_ key: String) -> String {
            (bundle.object(forInfoDictionaryKey: key) as? String)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        }
        return Self(
            endpoint: value("APPWRITE_ENDPOINT"),
            projectId: value("APPWRITE_PROJECT_ID"),
            databaseId: value("APPWRITE_DATABASE_ID"),
            settingsTableId: value("APPWRITE_SETTINGS_TABLE_ID")
        )
    }
}

public struct CloudPreferences: Codable, Sendable, Equatable {
    public var locale: String
    public var reducedMotion: Bool
    public var compactMonitor: Bool
    public var defaultMicrophoneEnabled: Bool
    public var updatedAt: Double

    public init(
        locale: String = "ru",
        reducedMotion: Bool = false,
        compactMonitor: Bool = false,
        defaultMicrophoneEnabled: Bool = true,
        updatedAt: Double = Date().timeIntervalSince1970
    ) {
        self.locale = locale
        self.reducedMotion = reducedMotion
        self.compactMonitor = compactMonitor
        self.defaultMicrophoneEnabled = defaultMicrophoneEnabled
        self.updatedAt = updatedAt
    }

    var dictionary: [String: Any] {
        [
            "locale": locale,
            "reduced_motion": reducedMotion,
            "compact_monitor": compactMonitor,
            "default_microphone_enabled": defaultMicrophoneEnabled,
            "updated_at": updatedAt,
        ]
    }
}

@MainActor
@Observable
public final class AppwriteAccountService {
    public private(set) var userId: String?
    public private(set) var displayName: String?
    public private(set) var errorMessage: String?
    public private(set) var isBusy = false

    public let configuration: AppwriteConfiguration
    let client: Client?
    let account: Account?

    public init(configuration: AppwriteConfiguration = .fromBundle()) {
        self.configuration = configuration
        if configuration.isConfigured {
            let client = Client()
                .setEndpoint(configuration.endpoint)
                .setProject(configuration.projectId)
            self.client = client
            account = Account(client)
        } else {
            client = nil
            account = nil
        }
    }

    public var isConfigured: Bool { configuration.isConfigured }
    public var isSignedIn: Bool { userId != nil }

    public func restoreSession() async {
        guard let account else { return }
        do {
            let user = try await account.get()
            userId = user.id
            displayName = user.name
            errorMessage = nil
        } catch {
            userId = nil
            displayName = nil
        }
    }

    public func signInWithApple() async {
        guard let account else {
            errorMessage = "Appwrite ещё не настроен."
            return
        }
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await account.createOAuth2Session(provider: .apple)
            await restoreSession()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func signOut() async {
        guard let account else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await account.deleteSession(sessionId: "current")
            userId = nil
            displayName = nil
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

@MainActor
public final class AppwriteSettingsRepository {
    private let configuration: AppwriteConfiguration
    private let database: TablesDB?
    private let defaults: UserDefaults
    private let cacheKeyPrefix = "mark.cloud.preferences"

    public init(
        accountService: AppwriteAccountService,
        defaults: UserDefaults = .standard
    ) {
        configuration = accountService.configuration
        if let client = accountService.client {
            database = TablesDB(client)
        } else {
            database = nil
        }
        self.defaults = defaults
    }

    public func cached(userId: String) -> CloudPreferences {
        guard
            let data = defaults.data(forKey: cacheKey(userId: userId)),
            let value = try? JSONDecoder().decode(CloudPreferences.self, from: data)
        else {
            return CloudPreferences()
        }
        return value
    }

    public func load(userId: String) async -> CloudPreferences {
        let local = cached(userId: userId)
        guard let database else { return local }
        do {
            let row = try await database.getRow(
                databaseId: configuration.databaseId,
                tableId: configuration.settingsTableId,
                rowId: userId,
                nestedType: CloudPreferences.self
            )
            let resolved = row.data.updatedAt >= local.updatedAt ? row.data : local
            cache(resolved, userId: userId)
            if local.updatedAt > row.data.updatedAt {
                try await save(local, userId: userId)
            }
            return resolved
        } catch {
            return local
        }
    }

    public func save(_ value: CloudPreferences, userId: String) async throws {
        cache(value, userId: userId)
        guard let database else { return }
        let role = Role.user(userId)
        _ = try await database.upsertRow(
            databaseId: configuration.databaseId,
            tableId: configuration.settingsTableId,
            rowId: userId,
            data: value.dictionary,
            permissions: [
                Permission.read(role),
                Permission.update(role),
                Permission.delete(role),
            ],
            nestedType: CloudPreferences.self
        )
    }

    private func cache(_ value: CloudPreferences, userId: String) {
        if let data = try? JSONEncoder().encode(value) {
            defaults.set(data, forKey: cacheKey(userId: userId))
        }
    }

    private func cacheKey(userId: String) -> String {
        "\(cacheKeyPrefix).\(userId)"
    }
}
