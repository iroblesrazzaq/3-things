import Foundation

/// Shared session / fragment rules for live extraction (app + eval parity).
enum VoiceDraftSessionLogic {
    static let minLiveCharacters = 8
    static let minFlushCharacters = 2

    static func normalize(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func shouldResetVoiceDraftSession(existing: VoiceDraftSessionState?, full: String) -> Bool {
        guard let existing, !existing.lastFullTranscript.isEmpty else { return false }
        if full == existing.lastFullTranscript { return false }
        if full.hasPrefix(existing.lastFullTranscript) { return false }
        return true
    }

    static func newTranscriptFragment(full: String, state: VoiceDraftSessionState?) -> String {
        guard let state,
              state.processedTranscriptCharacterCount > 0,
              state.processedTranscriptCharacterCount <= full.count
        else {
            return full
        }
        let idx = full.index(full.startIndex, offsetBy: state.processedTranscriptCharacterCount)
        return String(full[idx...]).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func buildRequest(
        snapshot: TranscriptSnapshot,
        session: VoiceDraftSessionState?
    ) -> ExtractionRequest {
        let clean = normalize(snapshot.fullText)
        let reset = shouldResetVoiceDraftSession(existing: session, full: clean)
        let existing = reset ? nil : session
        let fragment = reset ? clean : newTranscriptFragment(full: clean, state: existing)
        return ExtractionRequest(
            fullTranscript: clean,
            newFragment: fragment,
            existingState: existing,
            userFinishedSpeaking: snapshot.isFinal
        )
    }

    /// Mirrors client gates in `ToolVoiceDraftExtractor` before a model round.
    static func shouldSkipModelRound(_ request: ExtractionRequest) -> Bool {
        let fragment = request.newFragment.trimmingCharacters(in: .whitespacesAndNewlines)
        return fragment.isEmpty && !request.userFinishedSpeaking
    }

    /// Outcome when the model is not invoked (empty fragment while still recording).
    static func skippedOutcome(
        for request: ExtractionRequest
    ) -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        let env = VoiceDraftToolEnvironment(copying: request.existingState)
        if env.hasAnyTaskText() {
            return (
                .noDraft(reason: .unchanged),
                env.snapshotAfterProcessing(fullTranscript: request.fullTranscript)
            )
        }
        return (.noDraft(reason: .incomplete), env.snapshot())
    }

    /// Replay helper: sequence of (full, fragment, finished) for fixture `liveSnapshots`.
    static func liveSteps(
        from snapshots: [String],
        initialSession: VoiceDraftSessionState? = nil
    ) -> [(full: String, fragment: String, finished: Bool)] {
        guard !snapshots.isEmpty else { return [] }
        var session = initialSession
        var steps: [(String, String, Bool)] = []
        for (index, raw) in snapshots.enumerated() {
            let snapshot = TranscriptSnapshot(
                fullText: raw,
                isFinal: index == snapshots.count - 1
            )
            let request = buildRequest(snapshot: snapshot, session: session)
            steps.append((request.fullTranscript, request.newFragment, request.userFinishedSpeaking))
            if shouldSkipModelRound(request) {
                session = skippedOutcome(for: request).1
            } else {
                session = VoiceDraftSessionState(
                    selectedTasks: session?.selectedTasks ?? [],
                    extraCandidates: session?.extraCandidates ?? [],
                    processedTranscriptCharacterCount: request.fullTranscript.count,
                    lastFullTranscript: request.fullTranscript
                )
            }
        }
        return steps
    }
}
