import XCTest
@testable import MarkRemoteNetworking

final class BaseURLPolicyTests: XCTestCase {
    func testDefaultBaseURLIsLoopback() throws {
        let url = try BaseURLPolicy.makeBaseURL()
        XCTAssertEqual(url.scheme, "http")
        XCTAssertEqual(url.host, "127.0.0.1")
        XCTAssertEqual(url.port, 8765)
    }

    func testRejectsZeroZeroZeroZero() {
        XCTAssertThrowsError(
            try BaseURLPolicy.makeBaseURL(host: "0.0.0.0")
        ) { error in
            guard case BaseURLPolicyError.forbiddenHost("0.0.0.0") = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }

        XCTAssertThrowsError(
            try DesktopAPIClient(host: "0.0.0.0")
        ) { error in
            guard case DesktopAPIClientError.invalidBaseURL(.forbiddenHost("0.0.0.0")) = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }
    }

    func testRejectsZeroZeroZeroZeroEvenWhenNonLoopbackAllowed() {
        XCTAssertThrowsError(
            try BaseURLPolicy.makeBaseURL(host: "0.0.0.0", allowNonLoopback: true)
        ) { error in
            guard case BaseURLPolicyError.forbiddenHost = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }
    }

    func testRejectsNonLoopbackByDefault() {
        XCTAssertThrowsError(
            try BaseURLPolicy.makeBaseURL(host: "192.168.1.10")
        ) { error in
            guard case BaseURLPolicyError.nonLoopbackHost("192.168.1.10") = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }
    }

    func testAllowsNonLoopbackWhenExplicit() throws {
        let url = try BaseURLPolicy.makeBaseURL(host: "192.168.1.10", allowNonLoopback: true)
        XCTAssertEqual(url.host, "192.168.1.10")
    }

    func testAllowsLocalhost() throws {
        let url = try BaseURLPolicy.makeBaseURL(host: "localhost")
        XCTAssertEqual(url.host, "localhost")
    }
}
