import Foundation
import MarkRemoteModels

/// Injectable chat streaming surface. Production wires to Desktop Control `/v1/chat`.
public protocol ChatStreamingServing: Sendable {
    func streamChat(
        message: String,
        conversationId: String?,
        idempotencyKey: String
    ) -> AsyncThrowingStream<ChatStreamEvent, Error>
}

/// In-memory fake that emits scripted deltas for unit tests and previews.
public actor FakeChatStreamingClient: ChatStreamingServing {
    public var events: [ChatStreamEvent]
    public private(set) var requestCount = 0
    public private(set) var lastMessage: String?
    public private(set) var lastConversationId: String?
    public private(set) var lastIdempotencyKey: String?
    /// Delay between events (0 = immediate).
    public var eventDelayNanoseconds: UInt64
    public var shouldFailWith: Error?

    public init(
        events: [ChatStreamEvent] = [],
        eventDelayNanoseconds: UInt64 = 0
    ) {
        self.events = events
        self.eventDelayNanoseconds = eventDelayNanoseconds
    }

    public func setEvents(_ events: [ChatStreamEvent]) {
        self.events = events
    }

    public func setFailure(_ error: Error?) {
        shouldFailWith = error
    }

    nonisolated public func streamChat(
        message: String,
        conversationId: String?,
        idempotencyKey: String
    ) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                let snapshot = await self.beginRequest(
                    message: message,
                    conversationId: conversationId,
                    idempotencyKey: idempotencyKey
                )
                if let error = snapshot.failure {
                    continuation.finish(throwing: error)
                    return
                }
                for event in snapshot.events {
                    if Task.isCancelled {
                        continuation.finish(throwing: CancellationError())
                        return
                    }
                    if snapshot.delay > 0 {
                        try? await Task.sleep(nanoseconds: snapshot.delay)
                    }
                    if Task.isCancelled {
                        continuation.finish(throwing: CancellationError())
                        return
                    }
                    continuation.yield(event)
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    private struct Snapshot: Sendable {
        var events: [ChatStreamEvent]
        var delay: UInt64
        var failure: Error?
    }

    private func beginRequest(
        message: String,
        conversationId: String?,
        idempotencyKey: String
    ) -> Snapshot {
        requestCount += 1
        lastMessage = message
        lastConversationId = conversationId
        lastIdempotencyKey = idempotencyKey
        return Snapshot(events: events, delay: eventDelayNanoseconds, failure: shouldFailWith)
    }
}
