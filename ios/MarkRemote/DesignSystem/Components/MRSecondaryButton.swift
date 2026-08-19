import SwiftUI

public struct MRSecondaryButton: View {
    private let title: String
    private let systemImage: String?
    private let action: () -> Void

    public init(
        _ title: String,
        systemImage: String? = nil,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.systemImage = systemImage
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            labelContent
                .font(MRTypography.headline)
                .foregroundStyle(MRColor.accent)
                .frame(maxWidth: .infinity)
                .padding(.vertical, MRSpacing.sm)
                .padding(.horizontal, MRSpacing.md)
                .background(
                    RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous)
                        .strokeBorder(MRColor.accent, lineWidth: 1.5)
                )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }

    @ViewBuilder
    private var labelContent: some View {
        if let systemImage {
            Label(title, systemImage: systemImage)
        } else {
            Text(title)
        }
    }
}
