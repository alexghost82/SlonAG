import Foundation

/// Optional hook for future file / camera upload. Stubs never call network without injection.
public protocol ConversationAttachmentHandling: Sendable {
    func handleAttachFile() async
    func handleOpenCamera() async
}

/// Default no-op stubs used by ConversationView.
public struct StubConversationAttachmentHandler: ConversationAttachmentHandling {
    public init() {}

    public func handleAttachFile() async {}
    public func handleOpenCamera() async {}
}

/// Records stub invocations for tests.
public final class RecordingConversationAttachmentHandler: ConversationAttachmentHandling, @unchecked Sendable {
    public private(set) var attachCount = 0
    public private(set) var cameraCount = 0

    public init() {}

    public func handleAttachFile() async {
        attachCount += 1
    }

    public func handleOpenCamera() async {
        cameraCount += 1
    }
}
