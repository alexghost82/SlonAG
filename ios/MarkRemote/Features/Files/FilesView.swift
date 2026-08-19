import DesignSystem
import SwiftUI
import UniformTypeIdentifiers

public struct FilesView: View {
    @Bindable private var viewModel: FilesViewModel
    @State private var showsFileImporter = false

    public init(viewModel: FilesViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        List {
            Section {
                MRSectionHeader("Файлы", subtitle: viewModel.allowlistNotice)
            }

            Section("Текущий путь") {
                Text(viewModel.currentPath)
                    .font(MRTypography.subheadline)
                    .foregroundStyle(MRColor.secondaryLabel)
                    .textSelection(.enabled)
                if viewModel.canGoUp {
                    Button("На уровень выше") {
                        Task { await viewModel.goUp() }
                    }
                }
                Button("Загрузить файл") {
                    showsFileImporter = true
                }
                .disabled(viewModel.isLoading)
            }

            if let errorMessage = viewModel.errorMessage {
                Section {
                    Text(errorMessage)
                        .font(MRTypography.subheadline)
                        .foregroundStyle(MRColor.warning)
                }
            }

            Section("Содержимое") {
                if viewModel.entries.isEmpty, !viewModel.isLoading {
                    MREmptyState(
                        title: "Пусто",
                        message: "В этой разрешённой папке нет элементов.",
                        systemImage: "folder"
                    )
                    .listRowBackground(Color.clear)
                } else {
                    ForEach(viewModel.entries) { entry in
                        Button {
                            Task { await viewModel.open(entry) }
                        } label: {
                            Label(
                                entry.name,
                                systemImage: entry.isDirectory ? "folder.fill" : "doc"
                            )
                            .foregroundStyle(MRColor.label)
                        }
                        .disabled(!entry.isDirectory || viewModel.isLoading)
                    }
                }
            }
        }
        .navigationTitle("Файлы")
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
        .fileImporter(
            isPresented: $showsFileImporter,
            allowedContentTypes: [.data],
            allowsMultipleSelection: false
        ) { result in
            guard case let .success(urls) = result, let url = urls.first else { return }
            Task { await viewModel.upload(url) }
        }
    }
}
