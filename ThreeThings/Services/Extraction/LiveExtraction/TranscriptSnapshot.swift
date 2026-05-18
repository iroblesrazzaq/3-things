import Foundation

/// Normalized cumulative transcript at a point in the live capture pipeline.
struct TranscriptSnapshot: Sendable, Equatable {
    var fullText: String
    /// True only for post-stop flush (maps to `userFinishedSpeaking` on extraction).
    var isFinal: Bool

    init(fullText: String, isFinal: Bool) {
        self.fullText = fullText
        self.isFinal = isFinal
    }
}

/// Built by the scheduler before each extraction round (model or client skip).
struct ExtractionRequest: Sendable, Equatable {
    var fullTranscript: String
    var newFragment: String
    var existingState: VoiceDraftSessionState?
    var userFinishedSpeaking: Bool

    var extractionContext: VoiceDraftExtractionContext {
        VoiceDraftExtractionContext(
            fullTranscript: fullTranscript,
            newFragment: newFragment,
            existingState: existingState,
            userFinishedSpeaking: userFinishedSpeaking
        )
    }
}
