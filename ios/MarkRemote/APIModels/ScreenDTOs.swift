import Foundation

/// POST `/v1/screen/capture`
public struct ScreenCaptureRequest: Codable, Sendable, Equatable {
    public var idempotencyKey: String

    public init(idempotencyKey: String) {
        self.idempotencyKey = idempotencyKey
    }
}

/// Capture metadata — no raw screenshot bytes required here.
public struct ScreenCaptureResponse: Codable, Sendable, Equatable {
    public var width: Int
    public var height: Int
    public var mimeType: String
    public var captureId: String
    public var approvalRequired: Bool

    public init(
        width: Int,
        height: Int,
        mimeType: String,
        captureId: String,
        approvalRequired: Bool = false
    ) {
        self.width = width
        self.height = height
        self.mimeType = mimeType
        self.captureId = captureId
        self.approvalRequired = approvalRequired
    }
}
