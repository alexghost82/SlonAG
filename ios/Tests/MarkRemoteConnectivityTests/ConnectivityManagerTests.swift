import XCTest
@testable import MarkRemote

/// Tests for ConnectivityManager connectivity logic.
final class ConnectivityManagerTests: XCTestCase {

    func testInitialState() {
        let manager = ConnectivityManager()
        XCTAssertEqual(manager.state, .disconnected)
        XCTAssertEqual(manager.currentTransport, .local)
        XCTAssertNil(manager.currentDevice)
    }

    func testPolicyDefaults() {
        let policy = ConnectivityPolicy.default
        XCTAssertTrue(policy.lanPreferred)
        XCTAssertTrue(policy.remoteFallback)
        XCTAssertTrue(policy.autoReconnect)
        XCTAssertEqual(policy.preferredMode, .auto)
    }

    func testConnectivityErrorLocalized() {
        let error = ConnectivityError.noDevicesAvailable
        XCTAssertNotNil(error.errorDescription)
        XCTAssertTrue(error.errorDescription!.contains("Не удалось"))

        let authError = ConnectivityError.authFailed("invalid token")
        XCTAssertTrue(authError.errorDescription!.contains("аутентификации"))

        let tlsError = ConnectivityError.tlsHandshakeFailed("cert expired")
        XCTAssertTrue(tlsError.errorDescription!.contains("TLS"))
    }

    func testConnectivityErrorEquatable() {
        XCTAssertEqual(
            ConnectivityError.noDevicesAvailable,
            ConnectivityError.noDevicesAvailable
        )
        XCTAssertNotEqual(
            ConnectivityError.noDevicesAvailable,
            ConnectivityError.alreadyConnecting
        )
    }

    func testLANDeviceConnectURL() {
        let device = LANDevice(
            name: "Test",
            host: "192.168.1.1",
            port: 8765,
            deviceID: "dev-1",
            displayName: "Test Desktop",
            fingerprint: "abc123",
            usesTLS: true
        )
        XCTAssertEqual(device.connectURL, "wss://192.168.1.1:8765")

        let device2 = LANDevice(
            name: "Test2",
            host: "192.168.1.2",
            port: 80,
            deviceID: "dev-2",
            displayName: "Plain",
            fingerprint: "",
            usesTLS: false
        )
        XCTAssertEqual(device2.connectURL, "ws://192.168.1.2:80")
    }

    func testLANDeviceEquatable() {
        let d1 = LANDevice(
            name: "N", host: "h", port: 80,
            deviceID: "id", displayName: "d", fingerprint: "f", usesTLS: true
        )
        let d2 = LANDevice(
            name: "N", host: "h", port: 80,
            deviceID: "id", displayName: "d", fingerprint: "f", usesTLS: true
        )
        XCTAssertEqual(d1, d2)
    }

    func testRemoteAdapterValidatesWSS() {
        let wssURL = URL(string: "wss://relay.example.com/ws")!
        XCTAssertTrue(RemoteAdapter.validateRemoteURL(wssURL))

        let wsURL = URL(string: "ws://relay.example.com/ws")!
        XCTAssertFalse(RemoteAdapter.validateRemoteURL(wsURL))

        let httpURL = URL(string: "http://relay.example.com/ws")!
        XCTAssertFalse(RemoteAdapter.validateRemoteURL(httpURL))
    }

    func testRemoteAdapterRejectsPlaintext() {
        let adapter = RemoteAdapter()
        // The default URL should be wss, so connect should not throw validation error.
        XCTAssertTrue(RemoteAdapter.validateRemoteURL(adapter.remoteURL))
    }
}
