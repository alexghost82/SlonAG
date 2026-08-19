import XCTest
import MarkRemoteSecurity

final class KeychainStoreTests: XCTestCase {
    func testInMemoryCredentialStoreRoundTripWithoutPrintingSecret() throws {
        let store = InMemoryCredentialStore()
        let secret = "super-secret-device-material"
        let credentials = DeviceCredentials(
            deviceId: "device-42",
            deviceSecret: secret,
            refreshToken: "refresh-secret",
            expiresAt: 99
        )

        try store.save(credentials)
        let loaded = try XCTUnwrap(store.load())
        XCTAssertEqual(loaded.deviceId, "device-42")
        XCTAssertEqual(loaded.deviceSecret, secret)
        XCTAssertEqual(loaded.refreshToken, "refresh-secret")

        let description = String(describing: loaded)
        let debug = String(reflecting: loaded)
        XCTAssertFalse(description.contains(secret))
        XCTAssertFalse(debug.contains(secret))
        XCTAssertFalse(description.contains("refresh-secret"))
        XCTAssertTrue(description.contains("***"))

        try store.delete()
        XCTAssertNil(try store.load())
    }

    func testMockBiometricAuthenticator() async throws {
        let mock = MockBiometricAuthenticator(isAvailable: true, result: .success(true))
        XCTAssertTrue(mock.canEvaluate())
        let ok = try await mock.evaluate(reason: "Approve high-risk action")
        XCTAssertTrue(ok)
        XCTAssertEqual(mock.evaluateCallCount, 1)
        XCTAssertEqual(mock.lastReason, "Approve high-risk action")
    }
}
