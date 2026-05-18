import Foundation

/// Client-owned extraction session: draft slots plus how much of the transcript has been applied.
struct VoiceDraftSessionState: Codable, Equatable, Sendable {
    var selectedTasks: [String]
    var extraCandidates: [String]
    /// Number of leading characters in `lastFullTranscript` already reflected in the draft by a completed tool round.
    var processedTranscriptCharacterCount: Int
    /// Last full transcript string this session was advanced against (normalized by caller).
    var lastFullTranscript: String

    init(
        selectedTasks: [String] = [],
        extraCandidates: [String] = [],
        processedTranscriptCharacterCount: Int = 0,
        lastFullTranscript: String = ""
    ) {
        self.selectedTasks = selectedTasks
        self.extraCandidates = extraCandidates
        self.processedTranscriptCharacterCount = processedTranscriptCharacterCount
        self.lastFullTranscript = lastFullTranscript
    }
}
