import Foundation

@MainActor
enum LiveExtractionRound: Sendable {
    case model(ExtractionRequest, TranscriptSnapshot)
    case clientSkip(
        outcome: VoiceDraftExtractionOutcome,
        newState: VoiceDraftSessionState,
        request: ExtractionRequest,
        snapshot: TranscriptSnapshot
    )
}

@MainActor
final class LiveExtractionScheduler {
    struct Configuration: Sendable {
        var debounceNanoseconds: UInt64 = 900_000_000
        var finalDedupWindowNanoseconds: UInt64 = 500_000_000
    }

    private(set) var latestSnapshot: TranscriptSnapshot?

    var sessionState: VoiceDraftSessionState?

    private let configuration: Configuration
    private let canExtract: () -> Bool
    private let onCustomizedWhileLive: () -> Void
    private let handleRound: (LiveExtractionRound) async -> Void

    private var debounceTask: Task<Void, Never>?
    private var debounceGeneration: UInt64 = 0
    private var extractionTask: Task<Void, Never>?
    private var lastDispatchedNormalized: String?
    private var lastFinalNormalized: String?
    private var lastFinalDispatchTime: ContinuousClock.Instant?

    init(
        configuration: Configuration = Configuration(),
        canExtract: @escaping () -> Bool,
        onCustomizedWhileLive: @escaping () -> Void = {},
        handleRound: @escaping (LiveExtractionRound) async -> Void
    ) {
        self.configuration = configuration
        self.canExtract = canExtract
        self.onCustomizedWhileLive = onCustomizedWhileLive
        self.handleRound = handleRound
    }

    func resetForNewRecording() {
        cancelPending()
        sessionState = nil
        latestSnapshot = nil
        lastDispatchedNormalized = nil
        lastFinalNormalized = nil
        lastFinalDispatchTime = nil
    }

    func ingestPartial(_ text: String) {
        let clean = VoiceDraftSessionLogic.normalize(text)
        latestSnapshot = TranscriptSnapshot(fullText: clean, isFinal: false)

        guard canExtract() else { return }
        guard clean.count >= VoiceDraftSessionLogic.minLiveCharacters else { return }

        scheduleDebouncedDispatch(clean: clean)
    }

    func ingestFinal(_ text: String) async {
        cancelDebounceOnly()
        let clean = VoiceDraftSessionLogic.normalize(text)
        latestSnapshot = TranscriptSnapshot(fullText: clean, isFinal: true)

        guard canExtract() else { return }
        guard clean.count >= VoiceDraftSessionLogic.minFlushCharacters else { return }

        if shouldSkipDuplicateFinal(clean) {
            return
        }
        recordFinalDispatch(clean)
        await dispatch(snapshot: TranscriptSnapshot(fullText: clean, isFinal: true))
    }

    func cancelPending() {
        debounceTask?.cancel()
        debounceTask = nil
        extractionTask?.cancel()
        extractionTask = nil
    }

    // MARK: - Private

    private func scheduleDebouncedDispatch(clean: String) {
        debounceTask?.cancel()
        debounceGeneration += 1
        let token = debounceGeneration
        let delay = configuration.debounceNanoseconds

        debounceTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: delay)
            guard let self else { return }
            guard !Task.isCancelled else { return }
            guard self.debounceGeneration == token else { return }
            await self.dispatch(snapshot: TranscriptSnapshot(fullText: clean, isFinal: false))
        }
    }

    private func cancelDebounceOnly() {
        debounceTask?.cancel()
        debounceTask = nil
    }

    private func shouldSkipDuplicateFinal(_ clean: String) -> Bool {
        guard clean == lastFinalNormalized, let lastFinalDispatchTime else { return false }
        let elapsed = lastFinalDispatchTime.duration(to: ContinuousClock.now)
        return elapsed < .nanoseconds(Int64(configuration.finalDedupWindowNanoseconds))
    }

    private func recordFinalDispatch(_ clean: String) {
        lastFinalNormalized = clean
        lastFinalDispatchTime = ContinuousClock.now
    }

    private func dispatch(snapshot: TranscriptSnapshot) async {
        guard canExtract() else {
            if !snapshot.isFinal {
                onCustomizedWhileLive()
            }
            return
        }

        let clean = VoiceDraftSessionLogic.normalize(snapshot.fullText)
        if !snapshot.isFinal, clean == lastDispatchedNormalized {
            return
        }

        extractionTask?.cancel()
        let task = Task { [weak self] in
            guard let self else { return }
            guard !Task.isCancelled else { return }

            let request = VoiceDraftSessionLogic.buildRequest(
                snapshot: snapshot,
                session: self.sessionState
            )

            self.lastDispatchedNormalized = clean

            if VoiceDraftSessionLogic.shouldSkipModelRound(request) {
                let skipped = VoiceDraftSessionLogic.skippedOutcome(for: request)
                self.sessionState = skipped.1
                await self.handleRound(
                    .clientSkip(
                        outcome: skipped.0,
                        newState: skipped.1,
                        request: request,
                        snapshot: snapshot
                    )
                )
                return
            }

            await self.handleRound(.model(request, snapshot))
        }
        extractionTask = task
        await task.value
    }
}
