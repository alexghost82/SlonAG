import XCTest
@testable import MarkRemoteApp

@MainActor
final class AppwriteSettingsRepositoryTests: XCTestCase {
    func testOfflineCacheIsIsolatedPerUserAndKeepsNonSecretFields() async throws {
        let suiteName = "AppwriteSettingsRepositoryTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let account = AppwriteAccountService(
            configuration: AppwriteConfiguration(
                endpoint: "",
                projectId: "",
                databaseId: "",
                settingsTableId: ""
            )
        )
        let repository = AppwriteSettingsRepository(
            accountService: account,
            defaults: defaults
        )
        let alice = CloudPreferences(
            locale: "en",
            reducedMotion: true,
            compactMonitor: true,
            defaultMicrophoneEnabled: false,
            updatedAt: 100
        )

        try await repository.save(alice, userId: "alice")

        XCTAssertEqual(repository.cached(userId: "alice"), alice)
        XCTAssertNotEqual(repository.cached(userId: "bob"), alice)
        let encoded = try XCTUnwrap(
            defaults.data(forKey: "mark.cloud.preferences.alice")
        )
        let serialized = try XCTUnwrap(String(data: encoded, encoding: .utf8))
        XCTAssertFalse(serialized.localizedCaseInsensitiveContains("token"))
        XCTAssertFalse(serialized.localizedCaseInsensitiveContains("secret"))
        XCTAssertFalse(serialized.localizedCaseInsensitiveContains("host"))
    }
}
