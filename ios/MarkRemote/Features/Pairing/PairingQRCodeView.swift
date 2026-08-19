import CoreImage.CIFilterBuiltins
import DesignSystem
import SwiftUI

/// Renders a QR code image from a pairing payload string (no network).
public struct PairingQRCodeView: View {
    public let payload: String
    public var dimension: CGFloat = 180

    public init(payload: String, dimension: CGFloat = 180) {
        self.payload = payload
        self.dimension = dimension
    }

    public var body: some View {
        Group {
            if let image = Self.makeImage(from: payload) {
                Image(decorative: image, scale: 1.0)
                    .interpolation(.none)
                    .resizable()
                    .scaledToFit()
                    .frame(width: dimension, height: dimension)
                    .accessibilityLabel("QR-код сопряжения")
            } else {
                Text("QR недоступен")
                    .font(MRTypography.caption)
                    .foregroundStyle(MRColor.secondaryLabel)
            }
        }
    }

    public static func makeImage(from string: String) -> CGImage? {
        guard !string.isEmpty else { return nil }
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        return context.createCGImage(scaled, from: scaled.extent)
    }
}
