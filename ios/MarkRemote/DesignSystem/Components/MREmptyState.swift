import SwiftUI

public struct MREmptyState: View {
    private let title: String
    private let message: String
    private let systemImage: String
    private let actionTitle: String?
    private let action: (() -> Void)?

    public init(
        title: String,
        message: String,
        systemImage: String = "tray",
        actionTitle: String? = nil,
        action: (() -> Void)? = nil
    ) {
        self.title = title
        self.message = message
        self.systemImage = systemImage
        self.actionTitle = actionTitle
        self.action = action
    }

    public var body: some View {
        VStack(spacing: MRSpacing.md) {
            Image(systemName: systemImage)
                .font(.system(size: 44, weight: .regular))
                .foregroundStyle(MRColor.tertiaryLabel)
                .accessibilityHidden(true)
            Text(title)
                .font(MRTypography.title)
                .foregroundStyle(MRColor.label)
                .multilineTextAlignment(.center)
            Text(message)
                .font(MRTypography.body)
                .foregroundStyle(MRColor.secondaryLabel)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                MRPrimaryButton(actionTitle, action: action)
                    .frame(maxWidth: 280)
                    .padding(.top, MRSpacing.xs)
            }
        }
        .padding(MRSpacing.lg)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }
}
