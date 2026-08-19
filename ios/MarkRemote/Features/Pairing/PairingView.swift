import DesignSystem
import SwiftUI

/// Pairing screen: one-time code, QR payload as text, paired device list, unpair.
public struct PairingView: View {
    @Bindable private var viewModel: PairingViewModel

    public init(viewModel: PairingViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: MRSpacing.lg) {
                sessionSection
                completeSection
                devicesSection
                if let errorMessage = viewModel.errorMessage {
                    Text(errorMessage)
                        .font(MRTypography.footnote)
                        .foregroundStyle(MRColor.danger)
                        .accessibilityLabel(errorMessage)
                }
            }
            .padding(MRSpacing.md)
        }
        .background(MRColor.groupedBackground)
        .navigationTitle("Сопряжение")
        .task {
            await viewModel.refreshPairedDevices()
        }
    }

    private var sessionSection: some View {
        VStack(alignment: .leading, spacing: MRSpacing.sm) {
            MRSectionHeader(
                "Одноразовый код",
                subtitle: "Покажите код или QR-полезную нагрузку на компьютере Mark."
            )

            if viewModel.oneTimeCode.isEmpty {
                Text("Код ещё не создан")
                    .font(MRTypography.body)
                    .foregroundStyle(MRColor.secondaryLabel)
            } else {
                Text(viewModel.oneTimeCode)
                    .font(MRTypography.monospacedDigit(.title2))
                    .foregroundStyle(MRColor.label)
                    .textSelection(.enabled)
                    .accessibilityLabel("Одноразовый код \(viewModel.oneTimeCode)")

                VStack(alignment: .leading, spacing: MRSpacing.xxs) {
                    Text("QR-код")
                        .font(MRTypography.caption)
                        .foregroundStyle(MRColor.secondaryLabel)
                    PairingQRCodeView(payload: viewModel.qrPayload)
                        .frame(maxWidth: .infinity, alignment: .center)
                    Text(viewModel.qrPayload)
                        .font(MRTypography.footnote)
                        .foregroundStyle(MRColor.label)
                        .textSelection(.enabled)
                        .accessibilityLabel("QR-полезная нагрузка")
                }
                .padding(MRSpacing.sm)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(MRColor.secondaryBackground, in: RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous))
            }

            MRPrimaryButton("Создать код", systemImage: "qrcode") {
                Task { await viewModel.startPairing() }
            }
            .disabled(viewModel.isBusy)
        }
    }

    private var completeSection: some View {
        VStack(alignment: .leading, spacing: MRSpacing.sm) {
            MRSectionHeader(
                "Подтверждение",
                subtitle: "Введите код с компьютера, если сопряжение инициировано там."
            )

            TextField("Код сопряжения", text: $viewModel.codeInput)
                .textFieldStyle(.roundedBorder)
                .font(MRTypography.monospacedDigit(.body))
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .accessibilityLabel("Код сопряжения")

            TextField("Имя устройства", text: $viewModel.deviceNameInput)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("Имя устройства")

            MRSecondaryButton("Завершить сопряжение", systemImage: "link") {
                Task { await viewModel.completePairing() }
            }
            .disabled(viewModel.isBusy)
        }
    }

    private var devicesSection: some View {
        VStack(alignment: .leading, spacing: MRSpacing.sm) {
            MRSectionHeader(
                "Сопряжённые устройства",
                subtitle: "Забыть устройство удаляет локальные учётные данные устройства."
            )

            if viewModel.pairedDevices.isEmpty {
                MREmptyState(
                    title: "Нет устройств",
                    message: "Сопрягите Mac через Mark Remote.",
                    systemImage: "laptopcomputer"
                )
                .frame(minHeight: 160)
            } else {
                ForEach(viewModel.pairedDevices) { device in
                    HStack(spacing: MRSpacing.sm) {
                        VStack(alignment: .leading, spacing: MRSpacing.xxs) {
                            Text(device.deviceName)
                                .font(MRTypography.headline)
                                .foregroundStyle(MRColor.label)
                            Text(device.deviceId)
                                .font(MRTypography.caption)
                                .foregroundStyle(MRColor.secondaryLabel)
                        }
                        Spacer(minLength: 0)
                        Button("Забыть") {
                            Task { await viewModel.unpair(deviceId: device.deviceId) }
                        }
                        .font(MRTypography.callout.weight(.semibold))
                        .foregroundStyle(MRColor.danger)
                        .disabled(viewModel.isBusy)
                        .accessibilityLabel("Забыть \(device.deviceName)")
                    }
                    .padding(MRSpacing.sm)
                    .background(MRColor.secondaryBackground, in: RoundedRectangle(cornerRadius: MRCornerRadius.md, style: .continuous))
                }
            }
        }
    }
}

#Preview("Сопряжение") {
    NavigationStack {
        PairingView(viewModel: PairingViewModel(service: PreviewPairingService()))
    }
}

#if DEBUG
private struct PreviewPairingService: PairingServing {
    func startPairing(idempotencyKey: String) async throws -> PairingSession {
        PairingSession(code: "123456", expiresAt: 0, qrPayload: "mark-remote://pair?code=123456")
    }

    func completePairing(code: String, deviceName: String, idempotencyKey: String) async throws -> PairedDeviceInfo {
        PairedDeviceInfo(deviceId: "dev_preview", deviceName: deviceName)
    }

    func unpair(deviceId: String) async throws {}

    func listPairedDevices() async -> [PairedDeviceInfo] {
        [PairedDeviceInfo(deviceId: "dev_preview", deviceName: "MacBook Pro")]
    }
}
#endif
