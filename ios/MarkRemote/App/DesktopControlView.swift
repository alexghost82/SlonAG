import DesignSystem
import MarkRemoteModels
import MarkRemoteNetworking
import Observation
import SwiftUI

@MainActor
@Observable
final class DesktopControlModel {
    private let client: DesktopAPIClient
    private let eventsClient: (any EventsClient)?
    private(set) var status: StatusResponse?
    private(set) var errorMessage: String?
    private(set) var isBusy = false

    init(client: DesktopAPIClient, eventsClient: (any EventsClient)? = nil) {
        self.client = client
        self.eventsClient = eventsClient
    }

    var visualState: MRAssistantVisualState {
        let raw = status?.assistantState?.lowercased() ?? ""
        return MRAssistantVisualState(rawValue: raw.uppercased()) ?? (status?.online == true ? .listening : .initialising)
    }

    func refresh() async {
        do {
            status = try await client.getStatus()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func control(_ action: String) async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await client.controlRuntime(action: action)
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func observe() async {
        guard let eventsClient else {
            await pollUntilCancelled()
            return
        }
        while !Task.isCancelled {
            do {
                try await eventsClient.connect()
                await refresh()
                while !Task.isCancelled {
                    _ = try await eventsClient.receive()
                    await refresh()
                }
            } catch {
                await eventsClient.disconnect()
                await refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
        await eventsClient.disconnect()
    }

    private func pollUntilCancelled() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: .seconds(2))
        }
    }
}

struct DesktopControlView: View {
    @State private var model: DesktopControlModel

    init(client: DesktopAPIClient, eventsClient: (any EventsClient)? = nil) {
        _model = State(
            initialValue: DesktopControlModel(
                client: client,
                eventsClient: eventsClient
            )
        )
    }

    var body: some View {
        ScrollView {
            VStack(spacing: MRSpacing.md) {
                header
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: MRSpacing.md) {
                        monitor
                            .frame(width: 220)
                        hud
                        controls
                            .frame(width: 260)
                    }
                    compactLayout
                }
            }
            .padding(MRSpacing.md)
        }
        .background(MRColor.background.ignoresSafeArea())
        .navigationTitle("Slon")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await model.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .accessibilityLabel("Обновить статус")
                .accessibilityIdentifier("control.refresh")
            }
        }
        .task {
            await model.observe()
        }
    }

    private var header: some View {
        HStack(spacing: MRSpacing.sm) {
            Text("Slon")
                .font(MRTypography.caption.weight(.bold))
                .foregroundStyle(MRColor.accentDim)
            Spacer()
            VStack(alignment: .center, spacing: 1) {
                Text("J.A.R.V.I.S")
                    .font(MRTypography.headline)
                    .foregroundStyle(MRColor.accent)
                Text("REMOTE SYSTEM INTERFACE")
                    .font(MRTypography.caption2)
                    .foregroundStyle(MRColor.tertiaryLabel)
            }
            Spacer()
            TimelineView(.periodic(from: .now, by: 1)) { timeline in
                VStack(alignment: .trailing, spacing: 1) {
                    Text(timeline.date, format: .dateTime.hour().minute().second())
                    Text(timeline.date, format: .dateTime.day().month(.abbreviated).year())
                }
                .font(MRTypography.caption2)
                .foregroundStyle(MRColor.secondaryLabel)
            }
        }
        .padding(.horizontal, MRSpacing.sm)
    }

    private var compactLayout: some View {
        VStack(spacing: MRSpacing.md) {
            hud
            monitor
            controls
        }
    }

    private var hud: some View {
        MRPanel {
            VStack(spacing: MRSpacing.sm) {
                Text("J.A.R.V.I.S")
                    .font(MRTypography.largeTitle)
                    .foregroundStyle(MRColor.accent)
                    .minimumScaleFactor(0.65)
                Text("JUST A RATHER VERY INTELLIGENT SYSTEM")
                    .font(MRTypography.caption2)
                    .foregroundStyle(MRColor.tertiaryLabel)
                    .multilineTextAlignment(.center)
                MRHudView(state: model.visualState)
                    .frame(maxWidth: 330)
                Text(model.visualState.rawValue)
                    .font(MRTypography.headline)
                    .foregroundStyle(model.visualState.color)
                if let error = model.errorMessage {
                    Text(error)
                        .font(MRTypography.footnote)
                        .foregroundStyle(MRColor.danger)
                        .multilineTextAlignment(.center)
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    private var monitor: some View {
        MRPanel {
            VStack(alignment: .leading, spacing: MRSpacing.sm) {
                panelTitle("◈ SYS MONITOR")
                metric("CPU", model.status?.systemMetrics?.cpuPercent, suffix: "%")
                metric("MEM", model.status?.systemMetrics?.memoryPercent, suffix: "%")
                metric("NET", model.status?.systemMetrics?.networkMBps, suffix: " MB/s")
                metric("GPU", model.status?.systemMetrics?.gpuPercent, suffix: "%")
                metric("TMP", model.status?.systemMetrics?.temperatureCelsius, suffix: "°C")
                Divider().overlay(MRColor.border)
                fact("UP", uptime(model.status?.systemMetrics?.uptimeSeconds))
                fact("PROC", model.status?.systemMetrics?.processCount.map(String.init) ?? "—")
                fact("OS", model.status?.systemMetrics?.osName ?? "—")
            }
        }
    }

    private var controls: some View {
        MRPanel {
            VStack(alignment: .leading, spacing: MRSpacing.sm) {
                panelTitle("◈ CONTROL")
                controlButton("MICROPHONE", icon: model.status?.micActive == true ? "mic.fill" : "mic.slash") {
                    await model.control(model.status?.micActive == true ? "mute" : "unmute")
                }
                controlButton("LOCAL TTS", icon: "waveform") {
                    await model.control("toggle_tts")
                }
                controlButton("LOCAL STT LISTEN", icon: "ear") {
                    await model.control("listen_stt")
                }
                controlButton("START", icon: "play.fill") {
                    await model.control("start")
                }
                controlButton("PAUSE", icon: "pause.fill") {
                    await model.control("pause")
                }
                controlButton("STOP", icon: "stop.fill") {
                    await model.control("stop")
                }
            }
        }
    }

    private func panelTitle(_ value: String) -> some View {
        Text(value)
            .font(MRTypography.headline)
            .foregroundStyle(MRColor.accent)
    }

    private func metric(_ name: String, _ value: Double?, suffix: String) -> some View {
        VStack(alignment: .leading, spacing: MRSpacing.xxs) {
            HStack {
                Text(name)
                Spacer()
                Text(value.map { String(format: "%.1f%@", $0, suffix) } ?? "—")
            }
            .font(MRTypography.caption)
            .foregroundStyle(MRColor.secondaryLabel)
            ProgressView(value: min(max(value ?? 0, 0), 100), total: 100)
                .tint(MRColor.accent)
        }
        .accessibilityElement(children: .combine)
    }

    private func fact(_ name: String, _ value: String) -> some View {
        HStack {
            Text(name)
            Spacer()
            Text(value)
        }
        .font(MRTypography.caption)
        .foregroundStyle(MRColor.secondaryLabel)
    }

    private func controlButton(
        _ title: String,
        icon: String,
        action: @escaping @MainActor () async -> Void
    ) -> some View {
        Button {
            Task { await action() }
        } label: {
            Label(title, systemImage: icon)
                .font(MRTypography.caption.weight(.bold))
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.bordered)
        .tint(MRColor.accent)
        .disabled(model.isBusy)
        .accessibilityIdentifier("control.\(title.lowercased().replacingOccurrences(of: " ", with: "_"))")
    }

    private func uptime(_ seconds: Double?) -> String {
        guard let seconds else { return "—" }
        let hours = Int(seconds) / 3600
        return String(format: "%02d:%02d", hours, (Int(seconds) % 3600) / 60)
    }
}
