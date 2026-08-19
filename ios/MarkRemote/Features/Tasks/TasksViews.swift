import DesignSystem
import SwiftUI

public struct TasksListView: View {
    @ObservedObject private var viewModel: TasksListViewModel
    private let onSelect: (TaskSummary) -> Void

    public init(
        viewModel: TasksListViewModel,
        onSelect: @escaping (TaskSummary) -> Void = { _ in }
    ) {
        self.viewModel = viewModel
        self.onSelect = onSelect
    }

    public var body: some View {
        List {
            Section {
                TextField(TasksStrings.promptLabel, text: $viewModel.draftPrompt, axis: .vertical)
                    .lineLimit(3...6)
                MRPrimaryButton(TasksStrings.createButton) {
                    Task { await viewModel.createFromDraft() }
                }
                .disabled(viewModel.isLoading)
            }

            Section {
                if viewModel.tasks.isEmpty, !viewModel.isLoading {
                    MREmptyState(
                        title: TasksStrings.emptyTitle,
                        message: TasksStrings.emptyMessage,
                        systemImage: "checklist"
                    )
                    .listRowBackground(Color.clear)
                } else {
                    ForEach(viewModel.tasks) { task in
                        Button {
                            onSelect(task)
                        } label: {
                            VStack(alignment: .leading, spacing: MRSpacing.xxs) {
                                Text(task.prompt ?? task.id)
                                    .font(MRTypography.body)
                                    .foregroundStyle(MRColor.label)
                                    .multilineTextAlignment(.leading)
                                Text(task.statusTitleRU)
                                    .font(MRTypography.caption)
                                    .foregroundStyle(MRColor.secondaryLabel)
                                if task.approvalRequired {
                                    Text(TasksStrings.approvalRequired)
                                        .font(MRTypography.caption)
                                        .foregroundStyle(MRColor.warning)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                    }
                }
            } header: {
                MRSectionHeader(TasksStrings.listTitle)
            }
        }
        .overlay {
            if viewModel.isLoading {
                ProgressView()
            }
        }
        .safeAreaInset(edge: .bottom) {
            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage)
                    .font(MRTypography.caption)
                    .foregroundStyle(MRColor.danger)
                    .padding(MRSpacing.sm)
                    .frame(maxWidth: .infinity)
                    .background(MRColor.secondaryBackground)
            }
        }
        .task {
            await viewModel.load()
        }
        .navigationTitle(TasksStrings.listTitle)
    }
}

public struct TaskDetailView: View {
    @ObservedObject private var viewModel: TaskDetailViewModel

    public init(viewModel: TaskDetailViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        List {
            if let detail = viewModel.detail {
                Section {
                    labeledRow(TasksStrings.statusLabel, detail.summary.statusTitleRU)
                    if let prompt = detail.summary.prompt {
                        labeledRow(TasksStrings.promptLabel, prompt)
                    }
                    labeledRow("ID", detail.summary.id)
                }

                Section {
                    if detail.plan.isEmpty {
                        Text("Шаги пока не сформированы.")
                            .font(MRTypography.body)
                            .foregroundStyle(MRColor.secondaryLabel)
                    } else {
                        ForEach(Array(detail.plan.enumerated()), id: \.element.id) { index, step in
                            HStack(alignment: .top, spacing: MRSpacing.sm) {
                                Text("\(index + 1).")
                                    .font(MRTypography.caption)
                                    .foregroundStyle(MRColor.tertiaryLabel)
                                VStack(alignment: .leading, spacing: MRSpacing.xxs) {
                                    Text(step.title)
                                        .font(MRTypography.body)
                                        .foregroundStyle(MRColor.label)
                                    Text(step.statusTitleRU)
                                        .font(MRTypography.caption)
                                        .foregroundStyle(
                                            detail.currentStepIndex == index
                                                ? MRColor.accent
                                                : MRColor.secondaryLabel
                                        )
                                }
                            }
                        }
                    }
                } header: {
                    MRSectionHeader(TasksStrings.planSection)
                }

                Section {
                    MRSecondaryButton(TasksStrings.pauseButton) {
                        Task { await viewModel.pause() }
                    }
                    .disabled(viewModel.isActing)
                    MRSecondaryButton(TasksStrings.retryButton) {
                        Task { await viewModel.retry() }
                    }
                    .disabled(viewModel.isActing)
                    MRPrimaryButton(TasksStrings.cancelButton) {
                        Task { await viewModel.cancel() }
                    }
                    .disabled(viewModel.isActing)
                }
            }
        }
        .overlay {
            if viewModel.isLoading {
                ProgressView()
            }
        }
        .safeAreaInset(edge: .bottom) {
            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage)
                    .font(MRTypography.caption)
                    .foregroundStyle(MRColor.danger)
                    .padding(MRSpacing.sm)
                    .frame(maxWidth: .infinity)
                    .background(MRColor.secondaryBackground)
            }
        }
        .task {
            await viewModel.load()
        }
        .navigationTitle(TasksStrings.detailTitle)
    }

    private func labeledRow(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: MRSpacing.xxs) {
            Text(title)
                .font(MRTypography.caption)
                .foregroundStyle(MRColor.secondaryLabel)
            Text(value)
                .font(MRTypography.body)
                .foregroundStyle(MRColor.label)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
