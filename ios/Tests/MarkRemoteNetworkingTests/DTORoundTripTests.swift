import XCTest
import MarkRemoteModels
@testable import MarkRemoteNetworking

final class DTORoundTripTests: XCTestCase {
    func testPairingStartRequestRoundTrip() throws {
        let original = PairingStartRequest(idempotencyKey: "idem-1")
        let data = try DesktopAPIJSON.encoder.encode(original)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["idempotency_key"] as? String, "idem-1")
        let decoded = try DesktopAPIJSON.decoder.decode(PairingStartRequest.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    func testPairingCompleteResponseRoundTrip() throws {
        let original = PairingCompleteResponse(
            deviceId: "dev-1",
            deviceSecret: "secret-once",
            expiresAt: 1_700_000_000
        )
        let data = try DesktopAPIJSON.encoder.encode(original)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["device_id"] as? String, "dev-1")
        XCTAssertEqual(json["device_secret"] as? String, "secret-once")
        XCTAssertEqual(json["expires_at"] as? Double, 1_700_000_000)
        let decoded = try DesktopAPIJSON.decoder.decode(PairingCompleteResponse.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    func testStatusResponseRoundTrip() throws {
        let original = StatusResponse(
            online: true,
            paired: true,
            providerId: "local",
            modelId: "mock-model",
            networkMode: "offline",
            privacyProfile: "fully_local",
            activeTasks: 2,
            pendingApprovals: 1
        )
        let data = try DesktopAPIJSON.encoder.encode(original)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["provider_id"] as? String, "local")
        XCTAssertEqual(json["active_tasks"] as? Int, 2)
        let decoded = try DesktopAPIJSON.decoder.decode(StatusResponse.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    func testChatRequestAndErrorEnvelopeRoundTrip() throws {
        let request = ChatRequest(
            message: "hello",
            idempotencyKey: "chat-1",
            conversationId: "conv-9"
        )
        let requestData = try DesktopAPIJSON.encoder.encode(request)
        let requestJSON = try XCTUnwrap(JSONSerialization.jsonObject(with: requestData) as? [String: Any])
        XCTAssertEqual(requestJSON["idempotency_key"] as? String, "chat-1")
        XCTAssertEqual(requestJSON["conversation_id"] as? String, "conv-9")

        let envelope = APIErrorEnvelope(code: "approval_required", message: "Needs approval.")
        let event = ChatStreamEvent(
            event: "approval_required",
            conversationId: "conv-9",
            approvalId: "appr-1",
            approvalRequired: true,
            error: envelope
        )
        let eventData = try DesktopAPIJSON.encoder.encode(event)
        let decoded = try DesktopAPIJSON.decoder.decode(ChatStreamEvent.self, from: eventData)
        XCTAssertEqual(decoded, event)
    }

    func testTaskApprovalModelMemoryScreenRoundTrip() throws {
        let taskList = TaskListResponse(tasks: [
            TaskInfo(id: "t1", status: "running", prompt: "do it", approvalRequired: true),
        ])
        XCTAssertEqual(
            try DesktopAPIJSON.decoder.decode(
                TaskListResponse.self,
                from: try DesktopAPIJSON.encoder.encode(taskList)
            ),
            taskList
        )

        let approvals = ApprovalListResponse(approvals: [
            ApprovalInfo(id: "a1", toolName: "shell", risk: "high", status: "pending", source: "chat"),
        ])
        XCTAssertEqual(
            try DesktopAPIJSON.decoder.decode(
                ApprovalListResponse.self,
                from: try DesktopAPIJSON.encoder.encode(approvals)
            ),
            approvals
        )

        let models = ModelsListResponse(models: [
            ModelInfo(id: "m1", providerId: "local", displayName: "Local", active: true),
        ])
        let modelsData = try DesktopAPIJSON.encoder.encode(models)
        let modelsJSON = try XCTUnwrap(JSONSerialization.jsonObject(with: modelsData) as? [String: Any])
        let first = try XCTUnwrap((modelsJSON["models"] as? [[String: Any]])?.first)
        XCTAssertEqual(first["provider_id"] as? String, "local")
        XCTAssertEqual(first["display_name"] as? String, "Local")

        let memory = MemoryGetResponse(entries: [
            MemoryEntry(id: "mem1", kind: "note", summary: "remember"),
        ])
        XCTAssertEqual(
            try DesktopAPIJSON.decoder.decode(
                MemoryGetResponse.self,
                from: try DesktopAPIJSON.encoder.encode(memory)
            ),
            memory
        )

        let screen = ScreenCaptureResponse(
            width: 1280,
            height: 720,
            mimeType: "image/png",
            captureId: "cap-1",
            approvalRequired: false
        )
        let screenData = try DesktopAPIJSON.encoder.encode(screen)
        let screenJSON = try XCTUnwrap(JSONSerialization.jsonObject(with: screenData) as? [String: Any])
        XCTAssertEqual(screenJSON["mime_type"] as? String, "image/png")
        XCTAssertEqual(screenJSON["capture_id"] as? String, "cap-1")
        XCTAssertEqual(
            try DesktopAPIJSON.decoder.decode(ScreenCaptureResponse.self, from: screenData),
            screen
        )
    }
}
