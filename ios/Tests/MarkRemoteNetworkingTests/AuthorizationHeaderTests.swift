import XCTest
import MarkRemoteModels
@testable import MarkRemoteNetworking

final class AuthorizationHeaderTests: XCTestCase {
    override func setUp() {
        super.setUp()
        URLProtocol.registerClass(MockURLProtocol.self)
    }

    override func tearDown() {
        URLProtocol.unregisterClass(MockURLProtocol.self)
        MockURLProtocol.requestHandler = nil
        super.tearDown()
    }

    func testAuthorizationBearerHeaderIsAttached() async throws {
        let expectedToken = "access-token-abc"
        let expectation = expectation(description: "request observed")

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer \(expectedToken)")
            XCTAssertEqual(request.url?.path, "/v1/status")
            expectation.fulfill()

            let body = """
            {"online":true,"paired":true,"active_tasks":0,"pending_approvals":0}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, body)
        }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: configuration)

        let client = try DesktopAPIClient(
            session: session,
            tokenProvider: StaticAccessTokenProvider(token: expectedToken)
        )
        let status = try await client.getStatus()
        XCTAssertTrue(status.online)
        XCTAssertTrue(status.paired)

        await fulfillment(of: [expectation], timeout: 2)
    }

    func testFakeEventsClient() async throws {
        let fake = FakeEventsClient(events: [
            DesktopEvent(type: "task_updated", payload: ["id": "t1"]),
        ])
        try await fake.connect()
        let event = try await fake.receive()
        XCTAssertEqual(event.type, "task_updated")
        XCTAssertEqual(event.payload["id"], "t1")
        await fake.disconnect()
    }
}

private final class MockURLProtocol: URLProtocol {
    nonisolated(unsafe) static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = MockURLProtocol.requestHandler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
