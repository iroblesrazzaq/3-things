import Foundation
import FoundationModels

/// Which pool a task slot refers to for revise/delete tools.
@Generable
enum VoiceDraftTaskPool: String, CaseIterable, Codable, Sendable {
    case selected
    case extra
}

/// Mutable draft state mutated by Foundation Models tools (and by the heuristic simulator path).
final class VoiceDraftToolEnvironment: @unchecked Sendable {
    var selectedTasks: [String]
    var extraCandidates: [String]
    var processedTranscriptCharacterCount: Int
    var lastFullTranscript: String
    /// Set when the model calls `no_action` during the current extraction round.
    var lastNoActionReason: NoDraftReason?

    init(copying state: VoiceDraftSessionState?) {
        if let s = state {
            selectedTasks = s.selectedTasks
            extraCandidates = s.extraCandidates
            processedTranscriptCharacterCount = s.processedTranscriptCharacterCount
            lastFullTranscript = s.lastFullTranscript
        } else {
            selectedTasks = []
            extraCandidates = []
            processedTranscriptCharacterCount = 0
            lastFullTranscript = ""
        }
        lastNoActionReason = nil
    }

    func recordNoAction(reason: NoDraftReason) {
        lastNoActionReason = reason
    }

    func snapshotAfterProcessing(fullTranscript: String) -> VoiceDraftSessionState {
        processedTranscriptCharacterCount = fullTranscript.count
        lastFullTranscript = fullTranscript
        return snapshot()
    }

    func snapshot() -> VoiceDraftSessionState {
        VoiceDraftSessionState(
            selectedTasks: selectedTasks,
            extraCandidates: extraCandidates,
            processedTranscriptCharacterCount: processedTranscriptCharacterCount,
            lastFullTranscript: lastFullTranscript
        )
    }

    func clearDraft() -> String {
        selectedTasks = []
        extraCandidates = []
        return "Cleared all tasks."
    }

    func addTask(text raw: String) -> String {
        let text = String(raw.prefix(100)).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return "Skipped empty task." }

        if selectedTasks.contains(where: { VoiceDraftPostProcessor.isSemanticDuplicate($0, text) }) {
            return "Skipped duplicate of a selected task."
        }
        if extraCandidates.contains(where: { VoiceDraftPostProcessor.isSemanticDuplicate($0, text) }) {
            return "Skipped duplicate of an extra."
        }

        if selectedTasks.count < 3 {
            selectedTasks.append(text)
            return "Added to selected."
        }
        extraCandidates.append(text)
        return "Added to extras (overflow)."
    }

    func deleteTask(pool: VoiceDraftTaskPool, slot: Int) -> String {
        switch pool {
        case .selected:
            guard selectedTasks.indices.contains(slot) else { return "Ignored delete: invalid selected index." }
            selectedTasks.remove(at: slot)
            return "Removed selected task."
        case .extra:
            guard extraCandidates.indices.contains(slot) else { return "Ignored delete: invalid extra index." }
            extraCandidates.remove(at: slot)
            return "Removed extra."
        }
    }

    func reviseTask(pool: VoiceDraftTaskPool, slot: Int, newText raw: String) -> String {
        let newText = String(raw.prefix(100)).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !newText.isEmpty else { return "Ignored revise: empty text." }
        switch pool {
        case .selected:
            guard selectedTasks.indices.contains(slot) else { return "Ignored revise: invalid selected index." }
            selectedTasks[slot] = newText
            return "Revised selected task."
        case .extra:
            guard extraCandidates.indices.contains(slot) else { return "Ignored revise: invalid extra index." }
            extraCandidates[slot] = newText
            return "Revised extra."
        }
    }

    /// Runs post-processor invariants (dedup, promote, overflow). Throws if nothing actionable remains.
    func normalizeToDraft(cleanedTranscript: String) throws -> VoiceExtractionDraft {
        let detectedMoreThanThree = selectedTasks.count + extraCandidates.count > 3
        return try VoiceDraftPostProcessor.buildDraft(
            selectedTasks: selectedTasks,
            extraCandidates: extraCandidates,
            detectedMoreThanThree: detectedMoreThanThree,
            containsActionableTasks: !selectedTasks.isEmpty,
            cleanedTranscript: cleanedTranscript
        )
    }

    func hasAnyTaskText() -> Bool {
        !selectedTasks.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }.isEmpty
    }
}
