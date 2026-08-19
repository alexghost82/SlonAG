import Foundation

/// Injectable speech capture (mic / STT). Real AVFoundation engines stay out of this module.
public protocol SpeechCapturing: Sendable {
    var isAvailable: Bool { get }
    func startCapture() async throws
    func stopCapture() async throws -> String
    func cancelCapture() async
}

/// Injectable TTS playback. Real engines stay out of this module.
public protocol SpeechPlaying: Sendable {
    var isSpeaking: Bool { get async }
    func speak(_ text: String) async throws
    func stop() async
}

public enum SpeechCaptureError: Error, Sendable, Equatable {
    case unavailable
    case alreadyCapturing
    case notCapturing
}

public enum SpeechPlaybackError: Error, Sendable, Equatable {
    case interrupted
    case failed
}

/// Fake mic/STT for tests and previews.
public final class FakeSpeechCapturer: SpeechCapturing, @unchecked Sendable {
    public var isAvailable: Bool
    public var transcriptOnStop: String
    public private(set) var isCapturing = false
    public private(set) var startCount = 0
    public private(set) var stopCount = 0
    public private(set) var cancelCount = 0

    public init(isAvailable: Bool = true, transcriptOnStop: String = "привет") {
        self.isAvailable = isAvailable
        self.transcriptOnStop = transcriptOnStop
    }

    public func startCapture() async throws {
        guard isAvailable else { throw SpeechCaptureError.unavailable }
        guard !isCapturing else { throw SpeechCaptureError.alreadyCapturing }
        startCount += 1
        isCapturing = true
    }

    public func stopCapture() async throws -> String {
        guard isCapturing else { throw SpeechCaptureError.notCapturing }
        stopCount += 1
        isCapturing = false
        return transcriptOnStop
    }

    public func cancelCapture() async {
        cancelCount += 1
        isCapturing = false
    }
}

/// Fake TTS for tests and previews.
public final class FakeSpeechPlayer: SpeechPlaying, @unchecked Sendable {
    public private(set) var spokenTexts: [String] = []
    public private(set) var stopCount = 0
    public var isSpeakingFlag = false
    /// When true, `speak` cooperatively checks cancellation / stop.
    public var speakDurationNanoseconds: UInt64 = 0

    private var speakTask: Task<Void, Error>?

    public init() {}

    public var isSpeaking: Bool {
        get async { isSpeakingFlag }
    }

    public func speak(_ text: String) async throws {
        spokenTexts.append(text)
        isSpeakingFlag = true
        defer { isSpeakingFlag = false }

        if speakDurationNanoseconds == 0 {
            return
        }

        try await withTaskCancellationHandler {
            try await Task.sleep(nanoseconds: speakDurationNanoseconds)
            if Task.isCancelled {
                throw SpeechPlaybackError.interrupted
            }
        } onCancel: {
            // stop() sets flag; cancellation surfaces as interrupted
        }
    }

    public func stop() async {
        stopCount += 1
        isSpeakingFlag = false
        speakTask?.cancel()
    }
}
