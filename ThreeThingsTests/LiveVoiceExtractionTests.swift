import XCTest
@testable import ThreeThings

@MainActor
final class LiveVoiceExtractionTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suiteName: String!

    override func setUp() {
        super.setUp()
        suiteName = "LiveVoiceExtractionTests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testDebouncedLiveExtractionRunsAfterDelay() async throws {
        let extractor = CountingHeuristicExtractor()
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: extractor,
            liveExtractionDebounceNanoseconds: 80_000_000
        )
        viewModel.selectedInputMode = .voice

        viewModel.updateVoiceTranscriptSnapshot("one, two, three, four, five, six, seven, eight")

        try await Task.sleep(nanoseconds: 200_000_000)

        XCTAssertEqual(extractor.callCount, 1)
        XCTAssertNotNil(viewModel.voiceDraft)
    }

    func testRapidTranscriptChangesCancelEarlierExtraction() async throws {
        let extractor = CountingHeuristicExtractor()
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: extractor,
            liveExtractionDebounceNanoseconds: 120_000_000
        )
        viewModel.selectedInputMode = .voice

        viewModel.updateVoiceTranscriptSnapshot("alpha, beta, gamma, delta, epsilon, zeta, eta, theta")
        try await Task.sleep(nanoseconds: 50_000_000)
        viewModel.updateVoiceTranscriptSnapshot("one, two, three, four, five, six, seven, eight")
        try await Task.sleep(nanoseconds: 400_000_000)

        XCTAssertEqual(extractor.callCount, 1)
        XCTAssertEqual(extractor.lastTranscript?.contains("one"), true)
    }

    func testUserEditsPauseLiveExtractionUntilResync() async throws {
        let extractor = CountingHeuristicExtractor()
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: extractor,
            liveExtractionDebounceNanoseconds: 80_000_000
        )
        viewModel.selectedInputMode = .voice

        viewModel.updateVoiceTranscriptSnapshot("one, two, three, four, five, six, seven, eight")
        try await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(extractor.callCount, 1)

        viewModel.updateTaskText(at: 0, text: "Manual override")
        extractor.callCount = 0

        viewModel.updateVoiceTranscriptSnapshot("nine, eight, seven, six, five, four, three, two")
        try await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(extractor.callCount, 0)

        await viewModel.applyLatestVoiceResync()
        XCTAssertGreaterThanOrEqual(extractor.callCount, 1)
    }

    func testStaleFlushResultIgnoredWhenTranscriptAdvances() async throws {
        let extractor = SlowHeuristicExtractor(delayNanoseconds: 200_000_000)
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: extractor,
            liveExtractionDebounceNanoseconds: 50_000_000
        )
        viewModel.selectedInputMode = .voice

        async let flushDone: Void = viewModel.flushLiveExtractionNow(
            transcript: "first, second, third, fourth, fifth, sixth, seventh, eighth"
        )
        try await Task.sleep(nanoseconds: 30_000_000)
        viewModel.updateVoiceTranscriptSnapshot("nine, ten, eleven, twelve, thirteen, fourteen, fifteen, sixteen")
        await flushDone
        try await Task.sleep(nanoseconds: 400_000_000)

        let joined = viewModel.plan.tasks.map(\.text).joined(separator: " ").lowercased()
        XCTAssertTrue(joined.contains("nine"), "Expected newer transcript to win; got: \(joined)")
        XCTAssertFalse(joined.contains("first"), "Stale flush should not keep first-transcript tasks; got: \(joined)")
    }

    func testLiveNoTaskExtractionSetsStatusWithoutSwitchingToText() async throws {
        let extractor = ThrowingEmptyModelExtractor()
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: extractor,
            liveExtractionDebounceNanoseconds: 60_000_000
        )
        viewModel.selectedInputMode = .voice

        viewModel.updateVoiceTranscriptSnapshot("some, words, here, now, please, thanks, extra, padding")
        try await Task.sleep(nanoseconds: 250_000_000)

        XCTAssertNil(viewModel.voiceDraft)
        XCTAssertTrue(viewModel.extractionStatus.contains("No tasks extracted"))
        XCTAssertEqual(viewModel.selectedInputMode, .voice)
    }

    func testOverflowFromLiveHeuristicExtraction() async throws {
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: HeuristicToolVoiceDraftExtractor(),
            liveExtractionDebounceNanoseconds: 60_000_000
        )
        viewModel.selectedInputMode = .voice

        viewModel.updateVoiceTranscriptSnapshot("a, b, c, d, e, f, g, h")
        try await Task.sleep(nanoseconds: 250_000_000)

        XCTAssertTrue(viewModel.plan.detectedMoreThanThree)
        XCTAssertFalse(viewModel.plan.extras.isEmpty)
    }

    func testNoActionablePreservesExistingDraft() async throws {
        let extractor = NoActionAfterDraftExtractor()
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: extractor,
            liveExtractionDebounceNanoseconds: 60_000_000
        )
        viewModel.selectedInputMode = .voice

        await viewModel.flushLiveExtractionNow(
            transcript: "call mom today please thanks extra"
        )
        XCTAssertEqual(viewModel.plan.tasks[0].text, "call mom")
        XCTAssertNotNil(viewModel.voiceDraft)

        await viewModel.flushLiveExtractionNow(
            transcript: "testing one two three four five six seven eight"
        )
        XCTAssertEqual(viewModel.plan.tasks[0].text, "call mom")
        XCTAssertNotNil(viewModel.voiceDraft)
        XCTAssertEqual(extractor.callCount, 2)
    }

    func testNoActionableClearsWhenNoPriorDraft() async throws {
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: AlwaysNoActionableExtractor(),
            liveExtractionDebounceNanoseconds: 60_000_000
        )
        viewModel.selectedInputMode = .voice

        await viewModel.flushLiveExtractionNow(
            transcript: "testing one two three four five six seven eight"
        )

        XCTAssertNil(viewModel.voiceDraft)
        XCTAssertTrue(viewModel.extractionStatus.contains("No tasks extracted"))
    }

    func testCorrectionReplacesDraftFromLatestTranscript() async throws {
        let extractor = ScriptedVoiceExtractor()
        let viewModel = AppViewModel(
            defaults: defaults,
            voiceDraftExtractor: extractor,
            liveExtractionDebounceNanoseconds: 60_000_000
        )
        viewModel.selectedInputMode = .voice

        viewModel.updateVoiceTranscriptSnapshot(
            "PHASE1 alpha, beta, gamma, delta, epsilon, zeta, eta, theta"
        )
        try await Task.sleep(nanoseconds: 250_000_000)
        XCTAssertEqual(viewModel.plan.tasks[0].text, "A")

        viewModel.updateVoiceTranscriptSnapshot(
            "PHASE2 one, two, three, four, five, six, seven, eight"
        )
        try await Task.sleep(nanoseconds: 250_000_000)
        XCTAssertEqual(viewModel.plan.tasks[0].text, "OnlyNew")
    }
}

// MARK: - Test doubles

private final class SlowHeuristicExtractor: VoiceDraftExtracting, @unchecked Sendable {
    let providerName = "SlowHeuristic"
    private let delayNanoseconds: UInt64
    private let inner = HeuristicToolVoiceDraftExtractor()

    init(delayNanoseconds: UInt64) {
        self.delayNanoseconds = delayNanoseconds
    }

    func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return try await inner.applyTranscript(context)
    }
}

private final class ThrowingEmptyModelExtractor: VoiceDraftExtracting, @unchecked Sendable {
    let providerName = "ThrowingEmpty"

    func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        _ = context
        throw VoiceDraftExtractionError.emptyModelOutput
    }
}

private final class ScriptedVoiceExtractor: VoiceDraftExtracting, @unchecked Sendable {
    let providerName = "Scripted"

    func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        let transcript = context.fullTranscript
        if transcript.contains("PHASE1") {
            let draft = try VoiceDraftPostProcessor.buildDraft(
                selectedTasks: ["A", "B", "C"],
                extraCandidates: [],
                detectedMoreThanThree: false,
                cleanedTranscript: transcript
            )
            let state = VoiceDraftSessionState(
                selectedTasks: draft.selectedTasks,
                extraCandidates: draft.extraCandidates,
                processedTranscriptCharacterCount: transcript.count,
                lastFullTranscript: transcript
            )
            return (.draft(draft), state)
        }
        if transcript.contains("PHASE2") {
            let draft = try VoiceDraftPostProcessor.buildDraft(
                selectedTasks: ["OnlyNew"],
                extraCandidates: [],
                detectedMoreThanThree: false,
                cleanedTranscript: transcript
            )
            let state = VoiceDraftSessionState(
                selectedTasks: draft.selectedTasks,
                extraCandidates: draft.extraCandidates,
                processedTranscriptCharacterCount: transcript.count,
                lastFullTranscript: transcript
            )
            return (.draft(draft), state)
        }
        throw VoiceDraftExtractionError.emptyModelOutput
    }
}

private final class NoActionAfterDraftExtractor: VoiceDraftExtracting, @unchecked Sendable {
    let providerName = "NoActionAfterDraft"
    private(set) var callCount = 0

    func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        callCount += 1
        let transcript = context.fullTranscript
        if callCount == 1 {
            let draft = try VoiceDraftPostProcessor.buildDraft(
                selectedTasks: ["call mom"],
                extraCandidates: [],
                detectedMoreThanThree: false,
                cleanedTranscript: transcript
            )
            let state = VoiceDraftSessionState(
                selectedTasks: draft.selectedTasks,
                extraCandidates: draft.extraCandidates,
                processedTranscriptCharacterCount: transcript.count,
                lastFullTranscript: transcript
            )
            return (.draft(draft), state)
        }
        let state = VoiceDraftSessionState(
            selectedTasks: ["call mom"],
            extraCandidates: [],
            processedTranscriptCharacterCount: transcript.count,
            lastFullTranscript: transcript
        )
        return (.noDraft(reason: .noActionable), state)
    }
}

private final class AlwaysNoActionableExtractor: VoiceDraftExtracting, @unchecked Sendable {
    let providerName = "AlwaysNoActionable"

    func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        let transcript = context.fullTranscript
        let state = VoiceDraftSessionState(
            processedTranscriptCharacterCount: transcript.count,
            lastFullTranscript: transcript
        )
        return (.noDraft(reason: .noActionable), state)
    }
}

private final class CountingHeuristicExtractor: VoiceDraftExtracting, @unchecked Sendable {
    let providerName = "CountingHeuristic"
    var callCount = 0
    private(set) var lastTranscript: String?
    private let inner = HeuristicToolVoiceDraftExtractor()

    func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
        callCount += 1
        lastTranscript = context.fullTranscript
        return try await inner.applyTranscript(context)
    }
}
