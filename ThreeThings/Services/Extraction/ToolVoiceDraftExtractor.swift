import Foundation
import FoundationModels

/// On-device tool-guided extraction: model mutates draft via tools; post-processor enforces invariants.
struct ToolVoiceDraftExtractor: VoiceDraftExtracting {
    let providerName = "Apple Foundation Models (tools)"

    func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        let full = context.fullTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !full.isEmpty else { throw VoiceDraftExtractionError.emptyTranscript }

        let model = SystemLanguageModel.default
        guard model.isAvailable else { throw VoiceDraftExtractionError.modelUnavailable }
        guard model.supportsLocale(.current) else { throw VoiceDraftExtractionError.localeUnsupported }

        let env = VoiceDraftToolEnvironment(copying: context.existingState)
        env.lastNoActionReason = nil
        let tools: [any Tool] = [
            AddTaskTool(environment: env),
            ReviseTaskTool(environment: env),
            DeleteTaskTool(environment: env),
            ClearDraftTool(environment: env),
            NoActionTool(environment: env)
        ]

        let instructions = Instructions {
            """
            You extract 1–3 focus tasks for TODAY from English voice text. Use ONLY the tools—never output JSON or lists in prose.
            Rules: delete cancelled items (never mind, scratch that, actually no, wait no); merge duplicate phrasings; drop future-day-only items (tomorrow, next week, not today); keep negative commitments (don't X, avoid X); collapse substeps under one parent task; never invent tasks not grounded in the transcript.
            If the new fragment is too short to interpret, or is filler/mic test with no actionable tasks, call no_action with reason incomplete or no_actionable.
            If nothing should change, call no_action with reason unchanged.
            Otherwise add, revise, or delete tasks to match the user's latest intent. Prefer revising over adding when correcting wording.
            """
        }

        let session = LanguageModelSession(model: model, tools: tools, instructions: instructions)

        let fragment = context.newFragment.trimmingCharacters(in: .whitespacesAndNewlines)
        let selectedLine = env.selectedTasks.joined(separator: " | ").isEmpty ? "(none)" : env.selectedTasks.joined(separator: " | ")
        let extrasLine = env.extraCandidates.joined(separator: " | ").isEmpty ? "(none)" : env.extraCandidates.joined(separator: " | ")

        let prompt = Prompt {
            "Full transcript:\n\(full)"
            "New fragment (since last applied position):\n\(fragment.isEmpty ? "(empty)" : fragment)"
            "User finished speaking: \(context.userFinishedSpeaking ? "yes" : "no")"
            "Current selected (order preserved): \(selectedLine)"
            "Current extras (overflow): \(extrasLine)"
            "Apply tools so the draft matches the transcript. If there are still no actionable tasks, call no_action."
        }

        _ = try await session.respond(to: prompt)

        if let reason = env.lastNoActionReason {
            if env.hasAnyTaskText() {
                return (.noDraft(reason: .unchanged), env.snapshotAfterProcessing(fullTranscript: full))
            }
            return (.noDraft(reason: reason), env.snapshotAfterProcessing(fullTranscript: full))
        }

        guard env.hasAnyTaskText() else {
            return (.noDraft(reason: .noActionable), env.snapshotAfterProcessing(fullTranscript: full))
        }

        do {
            let draft = try env.normalizeToDraft(cleanedTranscript: full)
            return (.draft(draft), env.snapshotAfterProcessing(fullTranscript: full))
        } catch {
            return (.noDraft(reason: .noActionable), env.snapshotAfterProcessing(fullTranscript: full))
        }
    }
}

private extension NoActionReasonArg {
    var noDraftReason: NoDraftReason {
        switch self {
        case .incomplete: return .incomplete
        case .no_actionable: return .noActionable
        case .unchanged: return .unchanged
        }
    }
}

// MARK: - Tools

private final class AddTaskTool: Tool {
    let name = "add_task"
    let description = "Append one actionable task for today (fills selected slots 1–3 first, then extras for overflow)."

    private let environment: VoiceDraftToolEnvironment

    init(environment: VoiceDraftToolEnvironment) {
        self.environment = environment
    }

    @Generable
    struct Arguments: Equatable {
        @Guide(description: "Short actionable task; keep the user's phrasing.")
        var text: String
    }

    func call(arguments: Arguments) async throws -> String {
        return environment.addTask(text: arguments.text)
    }
}

private final class ReviseTaskTool: Tool {
    let name = "revise_task"
    let description = "Replace the text of an existing selected or extra task by index."

    private let environment: VoiceDraftToolEnvironment

    init(environment: VoiceDraftToolEnvironment) {
        self.environment = environment
    }

    @Generable
    struct Arguments: Equatable {
        @Guide(description: "selected = top 3 slots; extra = overflow list.")
        var pool: VoiceDraftTaskPool
        @Guide(description: "0-based index into the chosen pool.")
        var slot: Int
        @Guide(description: "New task text.")
        var newText: String
    }

    func call(arguments: Arguments) async throws -> String {
        return environment.reviseTask(pool: arguments.pool, slot: arguments.slot, newText: arguments.newText)
    }
}

private final class DeleteTaskTool: Tool {
    let name = "delete_task"
    let description = "Remove a task from selected (0–2) or extras by index (e.g. after never mind)."

    private let environment: VoiceDraftToolEnvironment

    init(environment: VoiceDraftToolEnvironment) {
        self.environment = environment
    }

    @Generable
    struct Arguments: Equatable {
        var pool: VoiceDraftTaskPool
        var slot: Int
    }

    func call(arguments: Arguments) async throws -> String {
        return environment.deleteTask(pool: arguments.pool, slot: arguments.slot)
    }
}

private final class ClearDraftTool: Tool {
    let name = "clear_draft"
    let description = "Remove all selected tasks and extras when the user starts over."

    private let environment: VoiceDraftToolEnvironment

    init(environment: VoiceDraftToolEnvironment) {
        self.environment = environment
    }

    @Generable
    struct Arguments: Equatable {}

    func call(arguments: Arguments) async throws -> String {
        return environment.clearDraft()
    }
}

@Generable
enum NoActionReasonArg: String, CaseIterable {
    case incomplete
    case no_actionable
    case unchanged
}

private final class NoActionTool: Tool {
    let name = "no_action"
    let description = "Use when the fragment is incomplete, non-actionable filler, or requires no draft change."

    private let environment: VoiceDraftToolEnvironment

    init(environment: VoiceDraftToolEnvironment) {
        self.environment = environment
    }

    @Generable
    struct Arguments: Equatable {
        @Guide(description: "incomplete = fragment too short; no_actionable = mic test / ramble; unchanged = delta adds nothing.")
        var reason: NoActionReasonArg
    }

    func call(arguments: Arguments) async throws -> String {
        environment.recordNoAction(reason: arguments.reason.noDraftReason)
        return "Recorded no_action: \(arguments.reason.rawValue)."
    }
}
