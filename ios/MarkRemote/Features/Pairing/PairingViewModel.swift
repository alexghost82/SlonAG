import Foundation
import Observation

/// View-model for pairing: one-time code, QR payload text, paired devices, unpair.
@MainActor
@Observable
public final class PairingViewModel {
    public private(set) var oneTimeCode: String = ""
    public private(set) var qrPayload: String = ""
    public private(set) var expiresAt: Double?
    public private(set) var pairedDevices: [PairedDeviceInfo] = []
    public private(set) var isBusy: Bool = false
    public private(set) var errorMessage: String?
    public var deviceNameInput: String = "iPhone"
    public var codeInput: String = ""

    private let service: any PairingServing

    public init(service: any PairingServing) {
        self.service = service
    }

    public func refreshPairedDevices() async {
        pairedDevices = await service.listPairedDevices()
    }

    public func startPairing() async {
        guard !isBusy else { return }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        do {
            let session = try await service.startPairing(
                idempotencyKey: UUID().uuidString
            )
            oneTimeCode = session.code
            qrPayload = session.qrPayload
            expiresAt = session.expiresAt
            codeInput = session.code
        } catch {
            errorMessage = Self.russianPairingError
        }
    }

    public func completePairing() async {
        let code = codeInput.trimmingCharacters(in: .whitespacesAndNewlines)
        let name = deviceNameInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty, !name.isEmpty, !isBusy else { return }

        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        do {
            _ = try await service.completePairing(
                code: code,
                deviceName: name,
                idempotencyKey: UUID().uuidString
            )
            oneTimeCode = ""
            qrPayload = ""
            expiresAt = nil
            codeInput = ""
            await refreshPairedDevices()
        } catch {
            errorMessage = Self.russianPairingError
        }
    }

    public func unpair(deviceId: String) async {
        guard !isBusy else { return }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        do {
            try await service.unpair(deviceId: deviceId)
            await refreshPairedDevices()
        } catch {
            errorMessage = Self.russianPairingError
        }
    }

    private static let russianPairingError = "Не удалось выполнить сопряжение. Попробуйте ещё раз."
}
