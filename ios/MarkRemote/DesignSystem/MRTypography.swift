import SwiftUI

/// Type scale helpers backed by Dynamic Type–aware system fonts.
public enum MRTypography: Sendable {
    public static let largeTitle = Font.system(.largeTitle, design: .monospaced).weight(.bold)
    public static let title = Font.system(.title2, design: .monospaced).weight(.semibold)
    public static let headline = Font.system(.headline, design: .monospaced)
    public static let body = Font.system(.body, design: .monospaced)
    public static let callout = Font.system(.callout, design: .monospaced)
    public static let subheadline = Font.system(.subheadline, design: .monospaced)
    public static let footnote = Font.system(.footnote, design: .monospaced)
    public static let caption = Font.system(.caption, design: .monospaced)
    public static let caption2 = Font.system(.caption2, design: .monospaced)

    public static func monospacedDigit(_ style: Font.TextStyle = .body) -> Font {
        Font.system(style, design: .monospaced).monospacedDigit()
    }
}
