import SwiftUI

/// Slon visual tokens shared with the PyQt desktop HUD.
///
/// The product intentionally uses one high-contrast dark appearance on every
/// platform. Semantic names keep feature views decoupled from raw colors while
/// preserving the desktop cyan/orange/green state language.
public enum MRColor: Sendable {
    public static let background = Color(red: 0 / 255, green: 6 / 255, blue: 10 / 255)
    public static let secondaryBackground = Color(red: 1 / 255, green: 13 / 255, blue: 20 / 255)
    public static let groupedBackground = Color(red: 1 / 255, green: 15 / 255, blue: 24 / 255)
    public static let panel = secondaryBackground
    public static let panelElevated = groupedBackground
    public static let border = Color(red: 13 / 255, green: 51 / 255, blue: 71 / 255)
    public static let borderBright = Color(red: 26 / 255, green: 92 / 255, blue: 122 / 255)
    public static let label = Color(red: 216 / 255, green: 248 / 255, blue: 1)
    public static let secondaryLabel = Color(red: 90 / 255, green: 184 / 255, blue: 204 / 255)
    public static let tertiaryLabel = Color(red: 58 / 255, green: 138 / 255, blue: 154 / 255)
    public static let separator = border
    public static let accent = Color(red: 0, green: 212 / 255, blue: 1)
    public static let accentDim = Color(red: 0, green: 122 / 255, blue: 153 / 255)
    public static let accentGhost = Color(red: 0, green: 31 / 255, blue: 46 / 255)
    public static let success = Color(red: 0, green: 1, blue: 136 / 255)
    public static let warning = Color(red: 1, green: 107 / 255, blue: 0)
    public static let thinking = Color(red: 1, green: 204 / 255, blue: 0)
    public static let danger = Color(red: 1, green: 51 / 255, blue: 85 / 255)
    public static let muted = Color(red: 1, green: 51 / 255, blue: 102 / 255)
    public static let online = success
    public static let offline = secondaryLabel
}
