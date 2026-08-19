import SwiftUI

/// Bordered Slon panel used by both compact iPhone cards and iPad columns.
public struct MRPanel<Content: View>: View {
    private let content: Content

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    public var body: some View {
        content
            .padding(MRSpacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(MRColor.panel)
            .overlay {
                RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous)
                    .stroke(MRColor.border, lineWidth: 1)
            }
            .clipShape(RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous))
    }
}
