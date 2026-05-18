import SwiftUI

struct VoiceCaptureView: View {
    @ObservedObject var viewModel: AppViewModel
    @ObservedObject var speechManager: SpeechCaptureManager
    /// When true, show a slimmer capture strip (e.g. while a draft already exists below).
    var compact: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 10 : 16) {
            if !compact {
                Text("Voice")
                    .font(.title3.bold())
                    .foregroundStyle(ThemePalette.primary)
            }

            statusView

            VoiceWaveformView(
                level: speechManager.currentAudioLevel,
                isRecording: speechManager.phase == .recording,
                compact: compact
            )

            recordToggleRow

            if !speechManager.latestTranscript.isEmpty,
               speechManager.phase == .recording || speechManager.phase == .idle || speechManager.phase == .transcribing {
                Text(speechManager.latestTranscript)
                    .font(.footnote)
                    .foregroundStyle(Color.primary)
                    .themeCard(cornerRadius: 12, padding: 10)
            }

            if viewModel.isExtracting,
               !speechManager.latestTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                HStack(alignment: .center, spacing: 10) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Turning speech into your 1–3 things…")
                        .font(.footnote)
                        .foregroundStyle(ThemePalette.muted)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Extracting tasks from transcript")
            }

            if !compact {
                Button("Type instead") {
                    speechManager.cancelRecording()
                    viewModel.returnToTextEntry()
                }
                .font(.subheadline.weight(.medium))
                .buttonStyle(ThemeTealLinkButtonStyle())
            } else {
                Button("Type instead") {
                    speechManager.cancelRecording()
                    viewModel.returnToTextEntry()
                }
                .font(.caption.weight(.medium))
                .buttonStyle(ThemeTealLinkButtonStyle())
            }

            if !viewModel.extractionStatus.isEmpty {
                Text(viewModel.extractionStatus)
                    .font(.footnote)
                    .foregroundStyle(ThemePalette.muted)
            }

            #if DEBUG
            if !speechManager.speechDiagnosticLine.isEmpty {
                Text(speechManager.speechDiagnosticLine)
                    .font(.caption2.monospaced())
                    .foregroundStyle(ThemePalette.muted)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(ThemePalette.inputFill, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .stroke(ThemePalette.border.opacity(0.6), lineWidth: 1)
                    )
            }
            #endif

#if DEBUG
            if !compact {
                DisclosureGroup("Eval fixtures (debug)") {
                    evalFixtureSection
                }
                .tint(ThemePalette.primary)
            }
#endif
        }
        .themeSectionCard(cornerRadius: compact ? 14 : 16, padding: compact ? 12 : 16)
        .onChange(of: speechManager.latestTranscript) { _, newValue in
            viewModel.updateVoiceTranscriptSnapshot(newValue)
        }
        .onChange(of: speechManager.phase) { _, newPhase in
            viewModel.setVoiceRecordingActive(newPhase == .recording)
        }
        .onAppear {
            viewModel.setVoiceRecordingActive(speechManager.isRecording)
            speechManager.onFinalTranscript = { [viewModel] transcript in
                Task {
                    await viewModel.ingestFinalTranscript(transcript)
                }
            }
        }
        .onDisappear {
            speechManager.onFinalTranscript = nil
        }
    }

    private var recordToggleRow: some View {
        let verticalPad: CGFloat = compact ? 10 : 14
        return HStack(spacing: 14) {
            if speechManager.phase == .recording {
                Button {
                    speechManager.stopRecording()
                } label: {
                    Label("Stop recording", systemImage: "stop.circle.fill")
                        .font(.headline)
                }
                .buttonStyle(ThemeRecordingStopButtonStyle(verticalPadding: verticalPad))
                .disabled(speechManager.phase == .requestingPermission || speechManager.phase == .transcribing)
            } else {
                Button {
                    switch speechManager.phase {
                    case .idle, .failed:
                        viewModel.resetVoiceCustomizationForNewRecording()
                        speechManager.startRecording()
                    case .requestingPermission, .recording, .transcribing:
                        break
                    }
                } label: {
                    Label("Start speaking", systemImage: "mic.circle.fill")
                        .font(.headline)
                }
                .buttonStyle(ThemePrimaryProminentButtonStyle(verticalPadding: verticalPad))
                .disabled(speechManager.phase == .requestingPermission || speechManager.phase == .transcribing)
            }

            if speechManager.canCancel, speechManager.phase == .recording {
                Button("Cancel", role: .cancel) {
                    speechManager.cancelRecording()
                }
                .font(.subheadline)
                .foregroundStyle(ThemePalette.muted)
            }
        }
    }

#if DEBUG
    private var evalFixtureSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("Sample", selection: $viewModel.selectedVoiceFixtureID) {
                ForEach(viewModel.voiceFixtures) { fixture in
                    Text(fixture.title).tag(fixture.id)
                }
            }
            .pickerStyle(.menu)

            Text(viewModel.selectedVoiceFixture.transcript)
                .font(.footnote)
                .foregroundStyle(Color.primary)
                .themeCard(cornerRadius: 10, padding: 10)

            Button("Generate draft from fixture") {
                viewModel.generateMockVoiceDraft()
            }
            .buttonStyle(ThemeSecondaryOutlineButtonStyle())
        }
    }
#endif

    @ViewBuilder
    private var statusView: some View {
        switch speechManager.phase {
        case .idle:
            if speechManager.errorMessage == nil, speechManager.latestTranscript.isEmpty {
                Text("Tap Start speaking, say your 1–3 things, then tap again to stop. Tasks update as you talk.")
                    .font(.footnote)
                    .foregroundStyle(ThemePalette.muted)
            } else if let error = speechManager.errorMessage {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(ThemePalette.overflow)
            } else {
                Text(viewModel.isExtracting ? "Updating your things…" : "Ready for more voice—or review below.")
                    .font(.footnote)
                    .foregroundStyle(ThemePalette.muted)
            }
        case .requestingPermission:
            Text("Requesting microphone & speech access…")
                .font(.footnote)
                .foregroundStyle(ThemePalette.muted)
        case .recording:
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    Image(systemName: "waveform.circle.fill")
                    Text("Listening… transcript updates live.")
                        .font(.footnote.weight(.semibold))
                }
                .foregroundStyle(ThemePalette.primary)
                if viewModel.isExtracting {
                    HStack(spacing: 6) {
                        ProgressView()
                            .controlSize(.mini)
                            .tint(ThemePalette.primary)
                        Text("Drafting tasks from what you've said so far…")
                            .font(.caption2)
                            .foregroundStyle(ThemePalette.muted)
                    }
                }
            }
        case .transcribing:
            HStack(alignment: .top, spacing: 8) {
                ProgressView()
                    .tint(ThemePalette.primary)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Finishing transcript…")
                        .font(.footnote)
                        .foregroundStyle(ThemePalette.muted)
                    if viewModel.isExtracting {
                        Text("Still updating your draft from the last transcript.")
                            .font(.caption2)
                            .foregroundStyle(ThemePalette.muted)
                    }
                }
            }
        case .failed(let message):
            Text(message)
                .font(.footnote)
                .foregroundStyle(ThemePalette.overflow)
        }
    }
}
