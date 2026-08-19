@preconcurrency import AVFoundation
import Foundation
import MarkRemoteFeatures
import Speech

final class NativeSpeechCapturer: NSObject, SpeechCapturing, @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "ru-RU"))
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var transcript = ""
    private var capturing = false

    var isAvailable: Bool {
        recognizer?.isAvailable == true
    }

    func startCapture() async throws {
        guard isAvailable else { throw SpeechCaptureError.unavailable }
        guard !capturing else { throw SpeechCaptureError.alreadyCapturing }
        guard await authorize() else { throw SpeechCaptureError.unavailable }

        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: .duckOthers)
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        #endif

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }
        lock.withLock {
            transcript = ""
            capturing = true
            self.request = request
        }
        task = recognizer?.recognitionTask(with: request) { [weak self] result, _ in
            guard let result else { return }
            self?.lock.withLock {
                self?.transcript = result.bestTranscription.formattedString
            }
        }
        engine.prepare()
        try engine.start()
    }

    func stopCapture() async throws -> String {
        guard lock.withLock({ capturing }) else {
            throw SpeechCaptureError.notCapturing
        }
        finishCapture()
        try? await Task.sleep(for: .milliseconds(150))
        return lock.withLock { transcript }
    }

    func cancelCapture() async {
        finishCapture()
    }

    private func finishCapture() {
        if engine.isRunning {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        request?.endAudio()
        task?.cancel()
        task = nil
        request = nil
        lock.withLock { capturing = false }
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: .notifyOthersOnDeactivation
        )
        #endif
    }

    private func authorize() async -> Bool {
        let speech = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
        guard speech else { return false }
        #if os(iOS)
        return await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission {
                continuation.resume(returning: $0)
            }
        }
        #else
        return true
        #endif
    }
}

final class NativeSpeechPlayer: NSObject, SpeechPlaying, AVSpeechSynthesizerDelegate,
    @unchecked Sendable
{
    private let synthesizer = AVSpeechSynthesizer()
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    var isSpeaking: Bool {
        get async { synthesizer.isSpeaking }
    }

    func speak(_ text: String) async throws {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return
        }
        try await withCheckedThrowingContinuation { continuation in
            lock.withLock {
                self.continuation?.resume(throwing: SpeechPlaybackError.interrupted)
                self.continuation = continuation
            }
            let utterance = AVSpeechUtterance(string: text)
            utterance.voice = AVSpeechSynthesisVoice(language: "ru-RU")
            synthesizer.speak(utterance)
        }
    }

    func stop() async {
        synthesizer.stopSpeaking(at: .immediate)
        resume(throwing: SpeechPlaybackError.interrupted)
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        resume()
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        resume(throwing: SpeechPlaybackError.interrupted)
    }

    private func resume(throwing error: Error? = nil) {
        let pending = lock.withLock {
            let value = continuation
            continuation = nil
            return value
        }
        if let error {
            pending?.resume(throwing: error)
        } else {
            pending?.resume()
        }
    }
}
