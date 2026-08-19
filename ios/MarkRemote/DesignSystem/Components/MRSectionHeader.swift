import SwiftUI

public struct MRSectionHeader: View {
    private let title: String
    private let subtitle: String?

    public init(_ title: String, subtitle: String? = nil) {
        self.title = title
        self.subtitle = subtitle
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: MRSpacing.xxs) {
            Text(title)
                .font(MRTypography.headline)
                .foregroundStyle(MRColor.label)
                .accessibilityAddTraits(.isHeader)
            if let subtitle {
                Text(subtitle)
                    .font(MRTypography.subheadline)
                    .foregroundStyle(MRColor.secondaryLabel)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}
