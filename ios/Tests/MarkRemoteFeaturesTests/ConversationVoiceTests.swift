import XCTest
import MarkRemoteModels
@testable import MarkRemoteFeatures

@MainActor
final class ConversationVoiceTests: XCTestCase {

    // MARK: - Conversation streaming

    func testStreamDeltasAppendToAssistantMessage() async {
        let client = FakeChatStreamingClient(events: [
            ChatStreamEvent(event: "delta", conversationId: "conv-1", delta: "При"),
            ChatStreamEvent(event: "delta", conversationId: "conv-1", delta: "вет"),
            ChatStreamEvent(event: "done", conversationId: "conv-1"),
        ])
        let vm = ConversationViewModel(chatClient: client)

        vm.send(text: "Здравствуй")
        await waitUntil(timeout: 1.0) { !vm.isStreaming }

        XCTAssertEqual(vm.conversationId, "conv-1")
        XCTAssertEqual(vm.messages.count, 2)
        XCTAssertEqual(vm.messages[0].role, .user)
        XCTAssertEqual(vm.messages[0].text, "Здравствуй")
        XCTAssertEqual(vm.messages[1].role, .assistant)
        XCTAssertEqual(vm.messages[1].text, "Привет")
        XCTAssertFalse(vm.messages[1].isStreaming)
        XCTAssertFalse(vm.isStreaming)
        XCTAssertFalse(vm.storesProviderAPIKeysOnDevice)
    }

    func testCancelInFlightStopsStreaming() async {
        let client = FakeChatStreamingClient(
            events: [
                ChatStreamEvent(event: "delta", delta: "часть"),
                ChatStreamEvent(event: "delta", delta: " ещё"),
                ChatStreamEvent(event: "done"),
            ],
            eventDelayNanoseconds: 50_000_000
        )
        let vm = ConversationViewModel(chatClient: client)

        vm.send(text: "долго")
        await waitUntil(timeout: 1.0) { vm.isStreaming }
        XCTAssertTrue(vm.canCancel)

        vm.cancelGeneration()

        XCTAssertFalse(vm.isStreaming)
        XCTAssertFalse(vm.canCancel)
        XCTAssertEqual(vm.messages.first?.role, .user)
        let assistant = vm.messages.last
        XCTAssertEqual(assistant?.role, .assistant)
        XCTAssertFalse(assistant?.isStreaming ?? true)
    }

    func testPendingApprovalChipsFromStream() async {
        let client = FakeChatStreamingClient(events: [
            ChatStreamEvent(event: "delta", delta: "нужно подтверждение"),
            ChatStreamEvent(
                event: "approval_required",
                approvalId: "appr-9",
                approvalRequired: true
            ),
            ChatStreamEvent(event: "done"),
        ])
        let vm = ConversationViewModel(chatClient: client)

        vm.send(text: "удали файл")
        await waitUntil(timeout: 1.0) { !vm.isStreaming }

        XCTAssertEqual(vm.pendingApprovals.count, 1)
        XCTAssertEqual(vm.pendingApprovals[0].id, "appr-9")
        XCTAssertEqual(vm.pendingApprovals[0].toolName, ConversationStrings.approvalChipFallback)

        vm.dismissApprovalChip(id: "appr-9")
        XCTAssertTrue(vm.pendingApprovals.isEmpty)
    }

    func testAttachmentAndCameraStubsDoNotUpload() async {
        let client = FakeChatStreamingClient()
        let attachments = RecordingConversationAttachmentHandler()
        let vm = ConversationViewModel(chatClient: client, attachmentHandler: attachments)

        await vm.attachFileStub()
        await vm.openCameraStub()

        XCTAssertEqual(vm.lastComposerAction, .openCamera)
        XCTAssertEqual(attachments.attachCount, 1)
        XCTAssertEqual(attachments.cameraCount, 1)
        let requestCount = await client.requestCount
        XCTAssertEqual(requestCount, 0)
    }

    func testRussianConversationStrings() {
        XCTAssertEqual(ConversationStrings.title, "Чат")
        XCTAssertEqual(ConversationStrings.send, "Отправить")
        XCTAssertEqual(ConversationStrings.cancelGeneration, "Остановить генерацию")
        XCTAssertFalse(ConversationStrings.noProviderKeysOnDevice.isEmpty)
        XCTAssertTrue(ConversationStrings.noProviderKeysOnDevice.contains("не хранятся"))
    }

    // MARK: - Push-to-talk machine

    func testPushToTalkStateMachineHappyPath() {
        var state = PushToTalkState.idle
        state = PushToTalkMachine.reduce(state: state, event: .press)
        XCTAssertEqual(state, .recording)
        state = PushToTalkMachine.reduce(state: state, event: .release)
        XCTAssertEqual(state, .processing)
        state = PushToTalkMachine.reduce(state: state, event: .transcriptReady)
        XCTAssertEqual(state, .speaking)
        state = PushToTalkMachine.reduce(state: state, event: .playbackFinished)
        XCTAssertEqual(state, .idle)
    }

    func testPushToTalkInterruptWhileSpeaking() {
        var state = PushToTalkState.speaking
        state = PushToTalkMachine.reduce(state: state, event: .interrupt)
        XCTAssertEqual(state, .interrupted)
        state = PushToTalkMachine.reduce(state: state, event: .reset)
        XCTAssertEqual(state, .idle)
    }

    func testPushToTalkBargeInFromSpeaking() {
        var state = PushToTalkState.speaking
        state = PushToTalkMachine.reduce(state: state, event: .press)
        XCTAssertEqual(state, .recording)
    }

    // MARK: - Voice session

    func testVoicePressReleaseCapturesTranscriptAndSpeaks() async {
        let capturer = FakeSpeechCapturer(transcriptOnStop: "тест голоса")
        let player = FakeSpeechPlayer()
        let voice = VoiceSessionController(capturer: capturer, player: player)

        await voice.press()
        XCTAssertEqual(voice.state, .recording)
        XCTAssertTrue(capturer.isCapturing)

        await voice.release()
        XCTAssertEqual(voice.lastTranscript, "тест голоса")
        XCTAssertEqual(player.spokenTexts, ["тест голоса"])
        XCTAssertEqual(voice.state, .idle)
        XCTAssertFalse(voice.storesProviderAPIKeysOnDevice)
    }

    func testVoiceInterruptTTSStopsPlayer() async {
        let capturer = FakeSpeechCapturer(transcriptOnStop: "ок")
        let player = FakeSpeechPlayer()
        player.speakDurationNanoseconds = 200_000_000
        let voice = VoiceSessionController(capturer: capturer, player: player)

        let speakTask = Task {
            await voice.speak("длинный ответ ассистента")
        }

        await waitUntil(timeout: 1.0) { await player.isSpeaking || voice.state == .speaking }
        await voice.interruptTTS()
        _ = await speakTask.result

        XCTAssertGreaterThanOrEqual(player.stopCount, 1)
        XCTAssertFalse(voice.isSpeaking)
        XCTAssertTrue(voice.state == .interrupted || voice.state == .idle)
    }

    func testVoiceUnavailableMicSetsRussianError() async {
        let capturer = FakeSpeechCapturer(isAvailable: false)
        let voice = VoiceSessionController(capturer: capturer, player: FakeSpeechPlayer())

        await voice.press()

        XCTAssertEqual(voice.state, .idle)
        XCTAssertEqual(voice.lastErrorMessage, VoiceStrings.micUnavailable)
    }

    func testRussianVoiceStrings() {
        XCTAssertEqual(VoiceStrings.title, "Голос")
        XCTAssertEqual(VoiceStrings.recording, "Запись…")
        XCTAssertEqual(VoiceStrings.interrupt, "Прервать")
        XCTAssertTrue(VoiceStrings.noProviderKeysOnDevice.contains("не хранятся"))
    }

    func testConversationViewModelRejectsEmptyDraft() {
        let vm = ConversationViewModel(chatClient: FakeChatStreamingClient())
        vm.draft = "   "
        XCTAssertFalse(vm.canSend)
        vm.sendDraft()
        XCTAssertTrue(vm.messages.isEmpty)
    }

    // MARK: - Helpers

    private func waitUntil(
        timeout: TimeInterval,
        pollNanoseconds: UInt64 = 5_000_000,
        condition: @escaping () async -> Bool
    ) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await condition() { return }
            try? await Task.sleep(nanoseconds: pollNanoseconds)
        }
    }
}
