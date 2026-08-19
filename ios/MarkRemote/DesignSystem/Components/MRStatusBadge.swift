import SwiftUI

public enum MRConnectionStatus: String, Sendable, CaseIterable {
    case online
    case offline

    public var titleRU: String {
        switch self {
        case .online: "Онлайн"
        case .offline: "Офлайн"
        }
    }

    public var systemImage: String {
        switch self {
        case .online: "circle.fill"
        case .offline: "circle"
        }
    }
}

public struct MRStatusBadge: View {
    private let status: MRConnectionStatus

    public init(_ status: MRConnectionStatus) {
        self.status = status
    }

    public var body: some View {
        Label(status.titleRU, systemImage: status.systemImage)
            .font(MRTypography.caption.weight(.semibold))
            .foregroundStyle(foreground)
            .padding(.horizontal, MRSpacing.sm)
            .padding(.vertical, MRSpacing.xxs)
            .background(background, in: Capsule())
            .accessibilityLabel(status.titleRU)
    }

    private var foreground: Color {
        switch status {
        case .online: MRColor.online
        case .offline: MRColor.offline
        }
    }

    private var background: Color {
        switch status {
        case .online: MRColor.online.opacity(0.15)
        case .offline: MRColor.secondaryBackground
        }
    }
}
