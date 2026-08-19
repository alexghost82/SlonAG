import SwiftUI

public struct MRPrimaryButton: View {
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
                .foregroundStyle(Color.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, MRSpacing.sm)
                .padding(.horizontal, MRSpacing.md)
                .background(MRColor.accent, in: RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous))
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
