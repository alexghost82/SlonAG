import SwiftUI

public enum MRAssistantVisualState: String, CaseIterable, Sendable {
    case initialising = "INITIALISING"
    case thinking = "THINKING"
    case listening = "LISTENING"
    case speaking = "SPEAKING"
    case processing = "PROCESSING"
    case muted = "MUTED"

    public var color: Color {
        switch self {
        case .initialising, .processing: MRColor.accent
        case .thinking: MRColor.thinking
        case .listening: MRColor.success
        case .speaking: MRColor.warning
        case .muted: MRColor.muted
        }
    }
}

/// Vector fallback for the desktop HUD. It deliberately does not depend on
/// the missing `face.png`, and respects Reduce Motion.
public struct MRHudView: View {
    public var state: MRAssistantVisualState
    public var level: Double

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    public init(state: MRAssistantVisualState, level: Double = 0.35) {
        self.state = state
        self.level = min(max(level, 0), 1)
    }

    public var body: some View {
        TimelineView(.animation(minimumInterval: reduceMotion ? 1 : 1 / 30)) { timeline in
            let time = timeline.date.timeIntervalSinceReferenceDate
            Canvas { context, size in
                draw(in: context, size: size, time: time)
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Slon")
        .accessibilityValue(state.rawValue)
    }

    private func draw(in context: GraphicsContext, size: CGSize, time: TimeInterval) {
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let radius = min(size.width, size.height) * 0.34
        let pulse = reduceMotion ? 1 : 1 + sin(time * 2.2) * 0.035

        for index in 0..<3 {
            let inset = CGFloat(index) * radius * 0.20
            let rect = CGRect(
                x: center.x - radius * pulse + inset,
                y: center.y - radius * pulse + inset,
                width: (radius * pulse - inset) * 2,
                height: (radius * pulse - inset) * 2
            )
            context.stroke(
                Path(ellipseIn: rect),
                with: .color(state.color.opacity(0.85 - Double(index) * 0.2)),
                style: StrokeStyle(lineWidth: index == 0 ? 2 : 1, dash: index == 1 ? [6, 5] : [])
            )
        }

        let coreRect = CGRect(
            x: center.x - radius * 0.48,
            y: center.y - radius * 0.48,
            width: radius * 0.96,
            height: radius * 0.96
        )
        context.fill(
            Path(ellipseIn: coreRect),
            with: .radialGradient(
                Gradient(colors: [state.color.opacity(0.35), MRColor.background.opacity(0.98)]),
                center: center,
                startRadius: 0,
                endRadius: radius * 0.55
            )
        )

        let barCount = 15
        let barWidth = max(2, size.width * 0.008)
        for index in 0..<barCount {
            let normalized = Double(index) / Double(barCount - 1)
            let wave = reduceMotion ? 0.5 : (sin(time * 5 + normalized * 9) + 1) / 2
            let height = size.height * (0.018 + CGFloat(wave * level) * 0.06)
            let x = center.x + (CGFloat(index) - CGFloat(barCount - 1) / 2) * barWidth * 2
            let rect = CGRect(x: x, y: center.y + radius * 0.70 - height / 2, width: barWidth, height: height)
            context.fill(Path(roundedRect: rect, cornerRadius: barWidth / 2), with: .color(state.color))
        }
    }
}
