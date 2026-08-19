import Foundation

/// Push-to-talk finite state machine states.
public enum PushToTalkState: String, Sendable, Equatable, CaseIterable {
    case idle
    case recording
    case processing
    case speaking
    case interrupted
}

/// Pure transitions for the push-to-talk / TTS interrupt machine.
public enum PushToTalkTransition: Sendable, Equatable {
    case press
    case release
    case transcriptReady
    case playbackStarted
    case playbackFinished
    case interrupt
    case reset
    case captureFailed
}

public enum PushToTalkMachine {
    public static func reduce(state: PushToTalkState, event: PushToTalkTransition) -> PushToTalkState {
        switch (state, event) {
        case (.idle, .press):
            return .recording
        case (.recording, .release):
            return .processing
        case (.recording, .interrupt), (.recording, .reset), (.recording, .captureFailed):
            return .idle
        case (.processing, .transcriptReady), (.processing, .playbackStarted):
            return .speaking
        case (.processing, .interrupt), (.processing, .reset), (.processing, .captureFailed):
            return .idle
        case (.processing, .playbackFinished):
            return .idle
        case (.speaking, .interrupt):
            return .interrupted
        case (.speaking, .playbackFinished), (.speaking, .reset):
            return .idle
        case (.speaking, .press):
            // Barge-in: interrupt TTS and start recording.
            return .recording
        case (.interrupted, .reset), (.interrupted, .playbackFinished), (.interrupted, .press):
            return event == .press ? .recording : .idle
        case (.idle, .reset), (.idle, .interrupt):
            return .idle
        default:
            return state
        }
    }
}
