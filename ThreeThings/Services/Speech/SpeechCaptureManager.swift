import AVFoundation
import Combine
import CoreGraphics
import Foundation

@MainActor
final class SpeechCaptureManager: ObservableObject {
    enum Phase: Equatable {
        case idle
        case requestingPermission
        case recording
        case transcribing
        case failed(String)
    }

    /// Smoothed normalized mic level (0…1) for the static level meter UI.
    @Published private(set) var currentAudioLevel: CGFloat = 0

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var latestTranscript: String = ""
    @Published private(set) var errorMessage: String?

    /// Called once when recording stops with the finalized transcript (before phase becomes idle).
    var onFinalTranscript: ((String) -> Void)?

    #if DEBUG
    /// Latest line from the live speech pipeline (device `SFSpeechLiveCapture` only). Shown in DEBUG UI.
    @Published private(set) var speechDiagnosticLine: String = ""
    private var speechDebugCancellable: AnyCancellable?
    #endif

    private let liveCapture: LiveSpeechCapturing
    private let permissionGate: any RecordingPermissionGating
    private let locale: Locale
    private var smoothedAudioLevel: CGFloat = 0
    private var audioBufferLevelCount = 0

    init(
        liveCapture: LiveSpeechCapturing? = nil,
        permissionGate: any RecordingPermissionGating = SystemRecordingPermissionGate(),
        locale: Locale = .current
    ) {
        self.liveCapture = liveCapture ?? LiveSpeechCaptureFactory.default()
        self.permissionGate = permissionGate
        self.locale = locale

        #if DEBUG
        speechDebugCancellable = NotificationCenter.default.publisher(for: .threeThingsSpeechPipelineDebug)
            .compactMap { $0.object as? String }
            .receive(on: DispatchQueue.main)
            .sink { [weak self] line in
                self?.speechDiagnosticLine = line
            }
        #endif
    }

    var isBusy: Bool {
        switch phase {
        case .idle, .failed:
            return false
        case .requestingPermission, .recording, .transcribing:
            return true
        }
    }

    var canRecord: Bool {
        switch phase {
        case .idle, .failed:
            return true
        case .requestingPermission, .recording, .transcribing:
            return false
        }
    }

    var canCancel: Bool {
        switch phase {
        case .requestingPermission, .recording, .transcribing:
            return true
        case .idle, .failed:
            return false
        }
    }

    var isRecording: Bool {
        if case .recording = phase { return true }
        return false
    }

    func startRecording() {
        guard canRecord else { return }

        errorMessage = nil
        latestTranscript = ""
        clearAudioLevels()
        #if DEBUG
        speechDiagnosticLine = ""
        #endif

        Task { await startRecordingAsync() }
    }

    private func startRecordingAsync() async {
        phase = .requestingPermission

        switch await permissionGate.ensureAuthorizedForRecording() {
        case .denied(let message):
            errorMessage = message
            phase = .failed(message)
            clearAudioLevels()
            return
        case .granted:
            break
        }

        do {
            try configureAudioSession()
            clearAudioLevels()
            try await liveCapture.start(
                locale: locale,
                onPartial: { [weak self] text in
                    self?.latestTranscript = text
                },
                onLevel: { [weak self] level in
                    self?.appendAudioLevel(level)
                }
            )
            phase = .recording
        } catch {
            let message = error.localizedDescription
            errorMessage = message
            phase = .failed(message)
            clearAudioLevels()
            try? await deactivateAudioSession()
        }
    }

    func stopRecording() {
        Task { await stopRecordingAsync() }
    }

    private func stopRecordingAsync() async {
        guard phase == .recording else { return }

        phase = .transcribing
        clearAudioLevels()

        do {
            let finalFromStop = try await liveCapture.stop()
            let trimmedFinal = finalFromStop.trimmingCharacters(in: .whitespacesAndNewlines)
            let trimmedLatest = latestTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
            let trimmed = trimmedFinal.isEmpty ? trimmedLatest : trimmedFinal

            guard !trimmed.isEmpty else {
                let message = "No speech detected. Try again or type instead."
                errorMessage = message
                latestTranscript = ""
                phase = .failed(message)
                clearAudioLevels()
                return
            }

            latestTranscript = trimmed
            errorMessage = nil
            onFinalTranscript?(trimmed)
            phase = .idle
            clearAudioLevels()
        } catch {
            let message = error.localizedDescription
            errorMessage = message
            latestTranscript = ""
            phase = .failed(message)
            clearAudioLevels()
        }
    }

    func cancelRecording() {
        liveCapture.cancel()
        errorMessage = nil
        latestTranscript = ""
        clearAudioLevels()
        #if DEBUG
        speechDiagnosticLine = ""
        #endif
        phase = .idle

        Task {
            try? await deactivateAudioSession()
        }
    }

    private func appendAudioLevel(_ level: Double) {
        guard phase == .recording || phase == .requestingPermission else { return }
        let raw = CGFloat(min(1, max(0, level)))
        let attack: CGFloat = 0.38
        let release: CGFloat = 0.18
        if raw > smoothedAudioLevel {
            smoothedAudioLevel = smoothedAudioLevel * attack + raw * (1 - attack)
        } else {
            smoothedAudioLevel = smoothedAudioLevel * (1 - release) + raw * release
        }

        audioBufferLevelCount += 1
        #if DEBUG
        if audioBufferLevelCount == 1 || audioBufferLevelCount % 200 == 0 {
            speechDiagnosticLine = "audio buffers appended: \(audioBufferLevelCount)"
        }
        #endif

        currentAudioLevel = smoothedAudioLevel
    }

    private func clearAudioLevels() {
        currentAudioLevel = 0
        smoothedAudioLevel = 0
        audioBufferLevelCount = 0
    }

    private func configureAudioSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .spokenAudio, options: [.defaultToSpeaker, .duckOthers])
        try session.setActive(true, options: [])
    }

    private func deactivateAudioSession() async throws {
        let session = AVAudioSession.sharedInstance()
        try session.setActive(false, options: .notifyOthersOnDeactivation)
    }
}
