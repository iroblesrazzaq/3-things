import SwiftUI

struct ExtractionReviewView: View {
    @ObservedObject var viewModel: AppViewModel
    @State private var isShowingLockConfirmation = false
    @State private var pendingReplaceExtraIndex: Int?

    var body: some View {
        ZStack {
            VStack(alignment: .leading, spacing: 16) {
                header
                selectedTasks
                extras
                validation
                actions
            }

            if viewModel.isExtracting {
                ZStack {
                    Color.primary.opacity(0.04)
                    VStack(spacing: 10) {
                        ProgressView()
                        Text("Updating draft…")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(ThemePalette.muted)
                    }
                }
                .allowsHitTesting(false)
                .transition(.opacity)
            }

            if let extraIdx = pendingReplaceExtraIndex,
               viewModel.plan.extras.indices.contains(extraIdx) {
                ReplaceThingPickerOverlay(
                    extraPreview: viewModel.plan.extras[extraIdx],
                    taskLines: (0..<3).map { viewModel.plan.tasks[$0].text },
                    onPick: { slot in
                        let pendingExtra = pendingReplaceExtraIndex
                        if let e = pendingExtra,
                           (0..<3).contains(slot),
                           viewModel.plan.extras.indices.contains(e) {
                            viewModel.replaceSelectedTask(at: slot, withExtraAt: e)
                        }
                        pendingReplaceExtraIndex = nil
                    },
                    onCancel: {
                        pendingReplaceExtraIndex = nil
                    }
                )
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.2), value: pendingReplaceExtraIndex)
        .animation(.easeInOut(duration: 0.22), value: viewModel.isExtracting)
        .onChange(of: viewModel.plan.extras) { _, extras in
            if let p = pendingReplaceExtraIndex, !extras.indices.contains(p) {
                pendingReplaceExtraIndex = nil
            }
        }
        .confirmationDialog(
            "Lock today's things?",
            isPresented: $isShowingLockConfirmation,
            titleVisibility: .visible
        ) {
            Button("Lock Today's Things", role: .destructive) {
                viewModel.confirmLockPlan()
            }

            Button("Keep Editing", role: .cancel) {}
        } message: {
            Text("You cannot change these tasks after confirming. They stay locked until the next focus day at 2:00 AM local time.")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            if viewModel.isVoiceRecordingActive {
                Text("Live draft — still listening")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ThemePalette.muted)
            }

            Text(viewModel.plan.detectedMoreThanThree ? "Pick what matters" : "Review voice draft")
                .font(.title3.bold())
                .foregroundStyle(viewModel.plan.detectedMoreThanThree ? ThemePalette.overflow : ThemePalette.primary)

            if viewModel.plan.detectedMoreThanThree {
                Text("I heard more than 3 things. Pick what actually matters today.")
                    .font(.footnote)
                    .foregroundStyle(ThemePalette.muted)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(ThemePalette.overflow.opacity(0.08), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .stroke(ThemePalette.overflow.opacity(0.35), lineWidth: 1)
                    )
            }

            if let cleanedTranscript = viewModel.voiceDraft?.cleanedTranscript,
               !cleanedTranscript.isEmpty {
                Text(cleanedTranscript)
                    .font(.footnote)
                    .foregroundStyle(Color.primary)
                    .themeCard(cornerRadius: 12, padding: 10)
            }
        }
    }

    private var selectedTasks: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Selected")
                .font(.caption)
                .foregroundStyle(ThemePalette.muted)
                .textCase(.uppercase)
                .tracking(0.5)

            ForEach(0..<3, id: \.self) { index in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Thing \(index + 1)")
                            .font(.caption2)
                            .foregroundStyle(ThemePalette.muted)

                        Spacer()

                        HStack(spacing: 8) {
                            Button {
                                viewModel.moveTask(from: index, to: index - 1)
                            } label: {
                                Image(systemName: "chevron.up")
                            }
                            .disabled(index == 0)

                            Button {
                                viewModel.moveTask(from: index, to: index + 1)
                            } label: {
                                Image(systemName: "chevron.down")
                            }
                            .disabled(index == 2)
                        }
                        .font(.caption)
                        .buttonStyle(.borderless)
                        .foregroundStyle(ThemePalette.muted)
                    }

                    TextField(
                        "What matters most?",
                        text: Binding(
                            get: { viewModel.plan.tasks[index].text },
                            set: { viewModel.updateTaskText(at: index, text: $0) }
                        ),
                        axis: .vertical
                    )
                    .textFieldStyle(.plain)
                    .lineLimit(3...8)
                    .themeInputField(cornerRadius: 12, isInvalid: viewModel.duplicateTaskIndexes.contains(index))

                    let count = viewModel.characterCount(at: index)
                    Text("\(count)/100")
                        .font(.caption2)
                        .foregroundStyle(count > 70 ? ThemePalette.warning : ThemePalette.muted)
                }
            }
        }
    }

    private var extras: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !viewModel.plan.extras.isEmpty {
                Text("Extras")
                    .font(.caption)
                    .foregroundStyle(viewModel.plan.detectedMoreThanThree ? ThemePalette.overflow : ThemePalette.muted)
                    .textCase(.uppercase)
                    .tracking(0.5)
            }

            ForEach(Array(viewModel.plan.extras.enumerated()), id: \.offset) { index, extra in
                VStack(alignment: .leading, spacing: 8) {
                    TextField(
                        "Extra candidate",
                        text: Binding(
                            get: { extra },
                            set: { viewModel.updateExtraCandidate(at: index, text: $0) }
                        ),
                        axis: .vertical
                    )
                    .textFieldStyle(.plain)
                    .lineLimit(2...6)
                    .themeInputField(cornerRadius: 12)

                    HStack {
                        Button("Replace…") {
                            pendingReplaceExtraIndex = index
                            viewModel.requestScrollRootToTop()
                        }
                        .foregroundStyle(ThemePalette.primary)

                        Button("Discard") {
                            viewModel.discardExtraCandidate(at: index)
                        }
                        .foregroundStyle(ThemePalette.overflow)
                    }
                    .font(.caption)
                    .buttonStyle(.borderless)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(ThemePalette.inputFill.opacity(0.5), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(ThemePalette.border.opacity(0.85), lineWidth: 1)
                )
            }
        }
    }

    @ViewBuilder
    private var validation: some View {
        if let message = viewModel.taskValidationMessage {
            Text(message)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(ThemePalette.overflow)
        }
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: 10) {
            if viewModel.userHasCustomizedVoicePlan {
                Button("Apply latest voice") {
                    Task { await viewModel.applyLatestVoiceResync() }
                }
                .buttonStyle(ThemeSecondaryOutlineButtonStyle())
            }

            Button("Lock Today's Things") {
                isShowingLockConfirmation = true
            }
            .buttonStyle(ThemePrimaryProminentButtonStyle())
            .disabled(!viewModel.canPresentLockConfirmation || viewModel.isVoiceRecordingActive)

            Button("Start Over With Typing") {
                viewModel.returnToTextEntry()
            }
            .buttonStyle(ThemeSecondaryOutlineButtonStyle())
        }
    }
}
