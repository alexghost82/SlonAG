import DesignSystem
import MarkRemoteFeatures
import MarkRemoteNetworking
import SwiftUI

/// Live desktop view: polls `GET /v1/screen/frame` (JPEG) while visible and
/// keeps the package `ScreenView` for on-demand capture metadata.
struct LiveScreenTabView: View {
    let environment: AppEnvironment
    let client: DesktopAPIClient

    @State private var frame: UIImage?
    @State private var errorMessage: String?
    @State private var isStreaming = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: MRSpacing.md) {
                frameSection
                Divider()
                ScreenView(
                    viewModel: ScreenViewModel(service: LiveScreenService(client: client))
                )
                .frame(minHeight: 260)
            }
            .padding(MRSpacing.md)
        }
        .background(MRColor.groupedBackground)
        .onDisappear { isStreaming = false }
    }

    @ViewBuilder
    private var frameSection: some View {
        Text("Живой экран")
            .font(MRTypography.title)

        if let frame {
            Image(uiImage: frame)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: MRCornerRadius.md))
        } else {
            RoundedRectangle(cornerRadius: MRCornerRadius.md)
                .fill(.quaternary)
                .frame(height: 180)
                .overlay(Text("Нет кадра").foregroundStyle(.secondary))
        }

        if let errorMessage {
            Text(errorMessage)
                .font(.footnote)
                .foregroundStyle(.red)
        }

        Button(isStreaming ? "Остановить трансляцию" : "Показать экран") {
            isStreaming.toggle()
            if isStreaming {
                Task { await streamLoop() }
            }
        }
        .buttonStyle(.borderedProminent)
    }

    private func streamLoop() async {
        while isStreaming, !Task.isCancelled {
            await loadFrame()
            try? await Task.sleep(for: .milliseconds(500))
        }
    }

    private func loadFrame() async {
        guard let provider = environment.tokenProvider else {
            errorMessage = "Нет сопряжения с рабочим столом."
            isStreaming = false
            return
        }
        do {
            guard let token = try await provider.accessToken() else {
                errorMessage = "Нет сопряжения с рабочим столом."
                isStreaming = false
                return
            }
            var request = URLRequest(url: client.baseURL.appendingPathComponent("v1/screen/frame"))
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            request.setValue("image/jpeg", forHTTPHeaderField: "Accept")

            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                errorMessage = "Рабочий стол не отдаёт кадр."
                isStreaming = false
                return
            }
            guard let image = UIImage(data: data) else {
                errorMessage = "Кадр повреждён."
                return
            }
            frame = image
            errorMessage = nil
        } catch {
            errorMessage = "Ошибка сети: \(error.localizedDescription)"
            isStreaming = false
        }
    }
}
