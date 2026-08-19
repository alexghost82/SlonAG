import DesignSystem
import MarkRemoteModels
import SwiftUI

public struct ModelsView: View {
    @Bindable private var viewModel: ModelsViewModel

    public init(viewModel: ModelsViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        List {
            Section {
                MRSectionHeader(
                    "Модели",
                    subtitle: "Выберите активную модель на сопряжённом компьютере. Ключи облачных API здесь не хранятся."
                )
            }

            if let errorMessage = viewModel.errorMessage {
                Section {
                    Text(errorMessage)
                        .font(MRTypography.subheadline)
                        .foregroundStyle(MRColor.warning)
                }
            }

            Section("Доступные") {
                if viewModel.models.isEmpty, !viewModel.isLoading {
                    MREmptyState(
                        title: "Нет моделей",
                        message: "Модели появятся после подключения к desktop-клиенту.",
                        systemImage: "cpu"
                    )
                    .listRowBackground(Color.clear)
                } else {
                    ForEach(viewModel.models) { model in
                        Button {
                            Task { await viewModel.activate(modelId: model.id) }
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: MRSpacing.xxs) {
                                    Text(model.displayName ?? model.id)
                                        .font(MRTypography.headline)
                                        .foregroundStyle(MRColor.label)
                                    Text(model.providerId)
                                        .font(MRTypography.caption)
                                        .foregroundStyle(MRColor.secondaryLabel)
                                }
                                Spacer()
                                if model.active {
                                    MRStatusBadge(.online)
                                }
                            }
                        }
                        .disabled(viewModel.isLoading || model.active)
                    }
                }
            }
        }
        .navigationTitle("Модели")
        .overlay {
            if viewModel.isLoading {
                ProgressView("Загрузка…")
            }
        }
        .task {
            await viewModel.load()
        }
        .refreshable {
            await viewModel.load()
        }
    }
}
