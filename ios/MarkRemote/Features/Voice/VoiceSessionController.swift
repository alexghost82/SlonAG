import Foundation
import Observation

/// Owns push-to-talk state, speech capture, and TTS interrupt.
@MainActor
@Observable
public final class VoiceSessionController {
    public private(set) var state: PushToTalkState = .idle
    public private(set) var lastTranscript: String?
    public private(set) var lastErrorMessage: String?
    public private(set) var isSpeaking = false

    public let storesProviderAPIKeysOnDevice = false

    private let capturer: any SpeechCapturing
    private let player: any SpeechPlaying
    private let transcriptHandler: (@Sendable (String) async throws -> String?)?
    private var playbackTask: Task<Void, Never>?

    public init(
        capturer: any SpeechCapturing = FakeSpeechCapturer(),
        player: any SpeechPlaying = FakeSpeechPlayer(),
        transcriptHandler: (@Sendable (String) async throws -> String?)? = nil
    ) {
        self.capturer = capturer
        self.player = player
        self.transcriptHandler = transcriptHandler
    }

    public var statusText: String {
        switch state {
        case .idle:
            return VoiceStrings.idleHint
        case .recording:
            return VoiceStrings.recording
        case .processing:
            return VoiceStrings.processing
        case .speaking:
            return VoiceStrings.speaking
        case .interrupted:
            return VoiceStrings.interrupted
        }
    }

    /// Begin push-to-talk (finger down). Interrupts TTS if speaking (barge-in).
    public func press() async {
        lastErrorMessage = nil

        if state == .speaking || isSpeaking {
            await stopPlayback(markInterrupted: true)
        }

        guard capturer.isAvailable else {
            lastErrorMessage = VoiceStrings.micUnavailable
            apply(.captureFailed)
            return
        }

        apply(.press)
        do {
            try await capturer.startCapture()
        } catch {
            lastErrorMessage = VoiceStrings.micUnavailable
            apply(.captureFailed)
        }
    }

    /// End push-to-talk (finger up): stop capture, then optionally speak reply text.
    public func release(speakReply reply: String? = nil) async {
        guard state == .recording else { return }
        apply(.release)

        let transcript: String
        do {
            transcript = try await capturer.stopCapture()
        } catch {
            await capturer.cancelCapture()
            lastErrorMessage = VoiceStrings.micUnavailable
            apply(.captureFailed)
            return
        }
        lastTranscript = transcript
        apply(.transcriptReady)
        do {
            let remoteReply: String?
            if let transcriptHandler, reply == nil {
                remoteReply = try await transcriptHandler(transcript)
            } else {
                remoteReply = nil
            }
            let textToSpeak = reply ?? remoteReply ?? transcript
            guard !textToSpeak.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                apply(.playbackFinished)
                return
            }
            await play(textToSpeak)
        } catch {
            lastErrorMessage = VoiceStrings.requestFailed
            apply(.captureFailed)
        }
    }

    /// Stop TTS playback and move to `.interrupted` when currently speaking.
    public func interruptTTS() async {
        await stopPlayback(markInterrupted: true)
    }

    /// Cancel recording or interrupt playback, then settle toward idle.
    public func interrupt() async {
        switch state {
        case .recording:
            await capturer.cancelCapture()
            apply(.interrupt)
        case .speaking, .processing:
            await stopPlayback(markInterrupted: true)
            if state == .interrupted {
                apply(.reset)
            }
        case .interrupted:
            apply(.reset)
        case .idle:
            break
        }
    }

    public func reset() async {
        playbackTask?.cancel()
        playbackTask = nil
        await capturer.cancelCapture()
        await player.stop()
        isSpeaking = false
        apply(.reset)
    }

    public func speak(_ text: String) async {
        await play(text)
    }

    private func play(_ text: String) async {
        playbackTask?.cancel()
        apply(.playbackStarted)
        isSpeaking = true

        let player = self.player
        let task = Task { [weak self] in
            guard let self else { return }
            do {
                try await player.speak(text)
                guard !Task.isCancelled else {
                    await MainActor.run { self.markPlaybackInterrupted() }
                    return
                }
                await MainActor.run { self.markPlaybackFinished() }
            } catch {
                await MainActor.run { self.markPlaybackInterrupted() }
            }
        }
        playbackTask = task
        await task.value
    }

    private func stopPlayback(markInterrupted: Bool) async {
        playbackTask?.cancel()
        playbackTask = nil
        await player.stop()
        isSpeaking = false
        if markInterrupted, state == .speaking {
            apply(.interrupt)
        }
    }

    private func markPlaybackFinished() {
        isSpeaking = false
        playbackTask = nil
        apply(.playbackFinished)
    }

    private func markPlaybackInterrupted() {
        isSpeaking = false
        playbackTask = nil
        apply(.interrupt)
    }

    private func apply(_ event: PushToTalkTransition) {
        state = PushToTalkMachine.reduce(state: state, event: event)
    }
}
