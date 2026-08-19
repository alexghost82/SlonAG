import Foundation
import MarkRemoteModels

/// Injectable on-demand screen capture client. No live video stream.
public protocol ScreenServing: Sendable {
    func captureScreen(idempotencyKey: String) async throws -> ScreenCaptureResponse
}
