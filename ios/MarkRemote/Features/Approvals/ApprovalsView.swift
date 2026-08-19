import DesignSystem
import SwiftUI

public struct ApprovalsView: View {
    @ObservedObject private var viewModel: ApprovalsViewModel
    @State private var showNarrowRuleHint = false

    public init(viewModel: ApprovalsViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        List {
            if viewModel.items.isEmpty, !viewModel.isLoading {
                MREmptyState(
                    title: ApprovalsStrings.emptyTitle,
                    message: ApprovalsStrings.emptyMessage,
                    systemImage: "hand.raised"
                )
                .listRowBackground(Color.clear)
            } else {
                Section {
                    ForEach(viewModel.items) { item in
                        Button {
                            viewModel.select(item)
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: MRSpacing.xxs) {
                                    Text(item.action)
                                        .font(MRTypography.body)
                                        .foregroundStyle(MRColor.label)
                                    Text(item.riskTitleRU)
                                        .font(MRTypography.caption)
                                        .foregroundStyle(riskColor(item.riskLevel))
                                }
                                Spacer()
                                if viewModel.selected?.id == item.id {
                                    Image(systemName: "checkmark.circle.fill")
                                        .foregroundStyle(MRColor.accent)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                } header: {
                    MRSectionHeader(ApprovalsStrings.title, subtitle: ApprovalsStrings.pendingOnlyHint)
                }

                if let selected = viewModel.selected {
                    detailSections(for: selected)
                    actionsSection(for: selected)
                }
            }
        }
        .overlay {
            if viewModel.isLoading || viewModel.isDeciding {
                ProgressView()
            }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: MRSpacing.xxs) {
                if let blockedReason = viewModel.blockedReason {
                    Text(blockedReason)
                        .font(MRTypography.caption)
                        .foregroundStyle(MRColor.warning)
                }
                if let errorMessage = viewModel.errorMessage {
                    Text(errorMessage)
                        .font(MRTypography.caption)
                        .foregroundStyle(MRColor.danger)
                }
            }
            .padding(MRSpacing.sm)
            .frame(maxWidth: .infinity)
            .background(MRColor.secondaryBackground)
            .opacity((viewModel.blockedReason != nil || viewModel.errorMessage != nil) ? 1 : 0)
        }
        .alert(ApprovalsStrings.narrowRule, isPresented: $showNarrowRuleHint) {
            Button("Понятно", role: .cancel) {}
        } message: {
            Text("Узкое правило можно добавить позже; сейчас доступны только «Разрешить один раз» и «Отклонить».")
        }
        .task {
            await viewModel.load()
        }
        .navigationTitle(ApprovalsStrings.title)
    }

    @ViewBuilder
    private func detailSections(for item: ApprovalItem) -> some View {
        Section {
            labeledRow(ApprovalsStrings.actionLabel, item.action)
            labeledRow(ApprovalsStrings.riskLabel, "\(item.riskTitleRU) (\(item.riskRaw))")
            if let source = item.source {
                labeledRow(ApprovalsStrings.sourceLabel, source)
            }
            // Exact args / path / URL: always show when present (never hide).
            if let exactArguments = item.exactArguments {
                labeledRow(ApprovalsStrings.argumentsLabel, exactArguments)
            }
            if let path = item.path {
                labeledRow(ApprovalsStrings.pathLabel, path)
            }
            if let url = item.url {
                labeledRow(ApprovalsStrings.urlLabel, url)
            }
            if let intent = item.intent {
                labeledRow(ApprovalsStrings.intentLabel, intent)
            }
            labeledRow(ApprovalsStrings.statusLabel, item.status)
        }
    }

    @ViewBuilder
    private func actionsSection(for item: ApprovalItem) -> some View {
        Section {
            MRPrimaryButton(ApprovalsStrings.allowOnce) {
                Task { await viewModel.allowOnce(id: item.id) }
            }
            .disabled(viewModel.isDeciding || !item.isPending)
            MRSecondaryButton(ApprovalsStrings.deny) {
                Task { await viewModel.deny(id: item.id) }
            }
            .disabled(viewModel.isDeciding || !item.isPending)
            Button(ApprovalsStrings.narrowRule) {
                showNarrowRuleHint = true
            }
            .font(MRTypography.subheadline)
            .foregroundStyle(MRColor.secondaryLabel)
        }
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
        .accessibilityElement(children: .combine)
    }

    private func riskColor(_ level: Int) -> Color {
        switch level {
        case 0, 1: return MRColor.secondaryLabel
        case 2: return MRColor.warning
        default: return MRColor.danger
        }
    }
}
