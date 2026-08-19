import DesignSystem
import MarkRemoteModels
import SwiftUI

public struct MemoryView: View {
    @Bindable private var viewModel: MemoryViewModel

    public init(viewModel: MemoryViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        List {
            Section {
                MRSectionHeader(
                    "Память",
                    subtitle: "Локальные записи desktop-клиента. Удаление требует подтверждения."
                )
            }

            if let errorMessage = viewModel.errorMessage {
                Section {
                    Text(errorMessage)
                        .font(MRTypography.subheadline)
                        .foregroundStyle(MRColor.warning)
                }
            }

            Section("Записи") {
                if viewModel.entries.isEmpty, !viewModel.isLoading {
                    MREmptyState(
                        title: "Память пуста",
                        message: "Записей пока нет.",
                        systemImage: "brain.head.profile"
                    )
                    .listRowBackground(Color.clear)
                } else {
                    ForEach(viewModel.entries) { entry in
                        VStack(alignment: .leading, spacing: MRSpacing.xxs) {
                            Text(entry.summary ?? entry.id)
                                .font(MRTypography.headline)
                                .foregroundStyle(MRColor.label)
                            Text(entry.kind)
                                .font(MRTypography.caption)
                                .foregroundStyle(MRColor.secondaryLabel)
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            Button(role: .destructive) {
                                viewModel.requestDelete(id: entry.id)
                            } label: {
                                Text("Удалить")
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("Память")
        .overlay {
            if viewModel.isLoading {
                ProgressView("Загрузка…")
            }
        }
        .confirmationDialog(
            "Удалить запись памяти?",
            isPresented: Binding(
                get: { viewModel.isConfirmingDelete },
                set: { if !$0 { viewModel.cancelDelete() } }
            ),
            titleVisibility: .visible
        ) {
            Button("Удалить", role: .destructive) {
                Task { await viewModel.confirmDelete() }
            }
            Button("Отмена", role: .cancel) {
                viewModel.cancelDelete()
            }
        } message: {
            Text("Это действие нельзя отменить с телефона.")
        }
        .task {
            await viewModel.load()
        }
        .refreshable {
            await viewModel.load()
        }
    }
}
