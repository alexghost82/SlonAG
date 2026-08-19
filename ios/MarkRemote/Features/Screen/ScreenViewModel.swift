import Foundation
import MarkRemoteModels
import Observation

/// Placeholder capture metadata shown until a real image payload is available.
public struct ScreenCapturePlaceholder: Sendable, Equatable {
    public var width: Int
    public var height: Int
    public var mimeType: String
    public var captureId: String
    public var approvalRequired: Bool

    public init(from response: ScreenCaptureResponse) {
        self.width = response.width
        self.height = response.height
        self.mimeType = response.mimeType
        self.captureId = response.captureId
        self.approvalRequired = response.approvalRequired
    }

    public var summaryRU: String {
        "\(width)×\(height), \(mimeType), id \(captureId)"
    }
}

@MainActor
@Observable
public final class ScreenViewModel {
    /// Tap-to-interact always requires an explicit confirmation flag before sending.
    public private(set) var interactionConfirmationRequired = true

    public private(set) var placeholder: ScreenCapturePlaceholder?
    public private(set) var isCapturing = false
    public private(set) var errorMessage: String?
    public private(set) var pendingTapNormalized: (x: Double, y: Double)?
    public private(set) var lastConfirmedTap: (x: Double, y: Double)?
    public private(set) var lastCaptureIdempotencyKey: String?

    private let service: any ScreenServing

    public init(service: any ScreenServing) {
        self.service = service
    }

    public func requestCapture() async {
        isCapturing = true
        errorMessage = nil
        defer { isCapturing = false }
        let key = IdempotencyKey.make()
        lastCaptureIdempotencyKey = key
        do {
            let response = try await service.captureScreen(idempotencyKey: key)
            placeholder = ScreenCapturePlaceholder(from: response)
            // Desktop may also require approval; keep local confirmation gate either way.
            if response.approvalRequired {
                interactionConfirmationRequired = true
            }
        } catch {
            errorMessage = "Не удалось получить снимок экрана: \(error.localizedDescription)"
        }
    }

    /// Records a tap candidate. Does not send interaction until `confirmPendingInteraction()`.
    public func proposeTap(normalizedX: Double, normalizedY: Double) {
        pendingTapNormalized = (normalizedX, normalizedY)
    }

    /// Returns `false` when confirmation is still required and not yet given.
    @discardableResult
    public func confirmPendingInteraction() -> Bool {
        guard let pending = pendingTapNormalized else { return false }
        guard interactionConfirmationRequired else {
            lastConfirmedTap = pending
            pendingTapNormalized = nil
            return true
        }
        lastConfirmedTap = pending
        pendingTapNormalized = nil
        return true
    }

    public func cancelPendingInteraction() {
        pendingTapNormalized = nil
    }

    /// Live video is explicitly out of scope for this phase.
    public var supportsLiveVideo: Bool { false }
}
