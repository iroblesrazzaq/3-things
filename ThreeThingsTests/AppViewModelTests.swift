import XCTest
@testable import ThreeThings

@MainActor
final class AppViewModelTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suiteName: String!

    override func setUp() {
        super.setUp()
        suiteName = "AppViewModelTests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testRejectsDuplicateDraftTasks() {
        let viewModel = makeViewModel()

        viewModel.updateTaskText(at: 0, text: "Write launch notes")
        viewModel.updateTaskText(at: 1, text: "  write launch notes  ")

        XCTAssertFalse(viewModel.canPresentLockConfirmation)
        XCTAssertEqual(viewModel.duplicateTaskIndexes, [0, 1])
        XCTAssertEqual(viewModel.taskValidationMessage, "Each thing needs to be distinct.")
    }

    func testLockTrimsAndDropsEmptyDraftTasks() {
        let viewModel = makeViewModel()

        viewModel.updateTaskText(at: 0, text: "  Write launch notes  ")
        viewModel.updateTaskText(at: 1, text: "")
        viewModel.updateTaskText(at: 2, text: "Ship TestFlight build")
        viewModel.confirmLockPlan()

        XCTAssertTrue(viewModel.plan.isLocked)
        XCTAssertEqual(viewModel.plan.tasks.map(\.text), ["Write launch notes", "Ship TestFlight build"])
        XCTAssertEqual(viewModel.plan.tasks.map(\.sortOrder), [0, 1])
        XCTAssertTrue(viewModel.plan.tasks.allSatisfy { !$0.isCompleted })
    }

    func testCompletionOnlyTogglesAfterLock() {
        let viewModel = makeViewModel()
        let draftID = viewModel.plan.tasks[0].id

        viewModel.toggleCompletion(taskID: draftID)
        XCTAssertFalse(viewModel.plan.tasks[0].isCompleted)

        viewModel.updateTaskText(at: 0, text: "Write launch notes")
        viewModel.confirmLockPlan()
        let lockedID = viewModel.plan.tasks[0].id
        viewModel.toggleCompletion(taskID: lockedID)

        XCTAssertTrue(viewModel.plan.tasks[0].isCompleted)
    }

    func testRolloverCreatesPendingFinalizationForIncompleteLockedDay() {
        var now = localDate(year: 2026, month: 4, day: 27, hour: 10)
        let dayOne = FocusDay.id(for: now)
        let viewModel = makeViewModel(dateProvider: { now })

        viewModel.updateTaskText(at: 0, text: "Write launch notes")
        viewModel.confirmLockPlan()

        now = localDate(year: 2026, month: 4, day: 28, hour: 10)
        let nextViewModel = makeViewModel(dateProvider: { now })

        XCTAssertEqual(nextViewModel.pendingFinalizationDayID, dayOne)
        XCTAssertFalse(nextViewModel.plan.isLocked)
        XCTAssertEqual(nextViewModel.plan.focusDayID, FocusDay.id(for: now))
    }

    func testRolloverAutoFinalizesCompleteLockedDay() {
        var now = localDate(year: 2026, month: 4, day: 27, hour: 10)
        let viewModel = makeViewModel(dateProvider: { now })

        viewModel.updateTaskText(at: 0, text: "Write launch notes")
        viewModel.confirmLockPlan()
        viewModel.toggleCompletion(taskID: viewModel.plan.tasks[0].id)

        now = localDate(year: 2026, month: 4, day: 28, hour: 10)
        let nextViewModel = makeViewModel(dateProvider: { now })

        XCTAssertNil(nextViewModel.pendingFinalizationDayID)
        XCTAssertEqual(nextViewModel.momentum7, 1)
    }

    func testFocusDayBoundaryKeepsPreTwoAmActivityOnPreviousDay() {
        let calendar = testCalendar
        let beforeBoundary = localDate(year: 2026, month: 4, day: 28, hour: 1, minute: 59)
        let atBoundary = localDate(year: 2026, month: 4, day: 28, hour: 2, minute: 0)

        XCTAssertEqual(FocusDay.id(for: beforeBoundary, calendar: calendar), "2026-04-27")
        XCTAssertEqual(FocusDay.id(for: atBoundary, calendar: calendar), "2026-04-28")
    }

    func testTrailingFocusDaysUseBoundaryAdjustedCurrentDay() {
        let calendar = testCalendar
        let beforeBoundary = localDate(year: 2026, month: 4, day: 28, hour: 1, minute: 59)

        XCTAssertEqual(
            FocusDay.trailingIDs(count: 3, endingAt: beforeBoundary, calendar: calendar),
            ["2026-04-25", "2026-04-26", "2026-04-27"]
        )
    }

    func testVoiceDraftStartsReviewWithSelectedTasksAndExtras() {
        let viewModel = makeViewModel()
        let draft = VoiceExtractionDraft(
            selectedTasks: ["Write launch email", "Fix onboarding", "Review PR"],
            extraCandidates: ["Pay rent", "Clean desk"],
            detectedMoreThanThree: true,
            cleanedTranscript: "Write launch email. Fix onboarding. Review PR. Pay rent. Clean desk."
        )

        viewModel.startVoiceDraftReview(from: draft)

        XCTAssertEqual(viewModel.selectedInputMode, .voice)
        XCTAssertEqual(viewModel.plan.source, .voice)
        XCTAssertEqual(viewModel.plan.tasks.map(\.text), ["Write launch email", "Fix onboarding", "Review PR"])
        XCTAssertEqual(viewModel.plan.extras, ["Pay rent", "Clean desk"])
        XCTAssertTrue(viewModel.plan.detectedMoreThanThree)
        XCTAssertEqual(viewModel.voiceDraft?.cleanedTranscript, draft.cleanedTranscript)
    }

    func testVoiceDraftReplacementMovesCurrentSelectionToExtras() {
        let viewModel = makeViewModel()
        viewModel.startVoiceDraftReview(from: VoiceExtractionDraft(
            selectedTasks: ["Write launch email", "Fix onboarding", "Review PR"],
            extraCandidates: ["Pay rent"],
            detectedMoreThanThree: true,
            cleanedTranscript: "Write launch email. Fix onboarding. Review PR. Pay rent."
        ))

        viewModel.replaceSelectedTask(at: 1, withExtraAt: 0)

        XCTAssertEqual(viewModel.plan.tasks.map(\.text), ["Write launch email", "Pay rent", "Review PR"])
        XCTAssertEqual(viewModel.plan.extras, ["Fix onboarding"])
        XCTAssertEqual(viewModel.voiceDraft?.extraCandidates, ["Fix onboarding"])
    }

    func testVoiceDraftDiscardAndExtraEdit() {
        let viewModel = makeViewModel()
        viewModel.startVoiceDraftReview(from: VoiceExtractionDraft(
            selectedTasks: ["Write launch email"],
            extraCandidates: ["Pay rent", "Clean desk"],
            cleanedTranscript: "Write launch email. Pay rent. Clean desk."
        ))

        viewModel.updateExtraCandidate(at: 1, text: "Clean the desk")
        viewModel.discardExtraCandidate(at: 0)

        XCTAssertEqual(viewModel.plan.extras, ["Clean the desk"])
        XCTAssertEqual(viewModel.voiceDraft?.extraCandidates, ["Clean the desk"])
    }

    func testVoiceDraftCapsCandidatesAtOneHundredCharacters() {
        let viewModel = makeViewModel()
        let longText = String(repeating: "a", count: 140)

        viewModel.startVoiceDraftReview(from: VoiceExtractionDraft(
            selectedTasks: [longText],
            extraCandidates: [longText],
            cleanedTranscript: longText
        ))

        XCTAssertEqual(viewModel.plan.tasks[0].text.count, 100)
        XCTAssertEqual(viewModel.plan.extras[0].count, 100)
    }

    func testLockingVoiceDraftPersistsVoiceSource() {
        let viewModel = makeViewModel()
        viewModel.startVoiceDraftReview(from: VoiceExtractionDraft(
            selectedTasks: ["Write launch email"],
            cleanedTranscript: "Write launch email."
        ))

        viewModel.confirmLockPlan()

        XCTAssertTrue(viewModel.plan.isLocked)
        XCTAssertEqual(viewModel.plan.source, .voice)
    }

    func testTranscriptExtractionRoutesToVoiceReviewWithExtrasAndOverflow() async {
        let viewModel = makeViewModel()

        await viewModel.extractTasksFromTranscript(
            "Write launch email. Fix onboarding. Review PR. Pay rent. Clean desk."
        )

        XCTAssertEqual(viewModel.selectedInputMode, .voice)
        XCTAssertEqual(viewModel.plan.source, .voice)
        XCTAssertEqual(viewModel.plan.tasks.map(\.text), ["Write launch email", "Fix onboarding", "Review PR"])
        XCTAssertEqual(viewModel.plan.extras, ["Pay rent", "Clean desk"])
        XCTAssertTrue(viewModel.plan.detectedMoreThanThree)
        XCTAssertEqual(viewModel.voiceDraft?.selectedTasks, ["Write launch email", "Fix onboarding", "Review PR"])
        XCTAssertEqual(viewModel.voiceDraft?.extraCandidates, ["Pay rent", "Clean desk"])
        XCTAssertEqual(
            viewModel.voiceDraft?.cleanedTranscript,
            "Write launch email. Fix onboarding. Review PR. Pay rent. Clean desk."
        )
        XCTAssertFalse(viewModel.canPresentLockConfirmation)
        XCTAssertEqual(viewModel.taskValidationMessage, "Resolve or discard extras before locking.")
    }

    func testOverflowDraftCanOnlyLockAfterExtrasAreDiscarded() {
        let viewModel = makeViewModel()
        viewModel.startVoiceDraftReview(from: VoiceExtractionDraft(
            selectedTasks: ["Write launch email", "Fix onboarding", "Review PR"],
            extraCandidates: ["Pay rent"],
            detectedMoreThanThree: true,
            cleanedTranscript: "Write launch email. Fix onboarding. Review PR. Pay rent."
        ))

        XCTAssertFalse(viewModel.canPresentLockConfirmation)
        XCTAssertEqual(viewModel.taskValidationMessage, "Resolve or discard extras before locking.")

        viewModel.discardExtraCandidate(at: 0)

        XCTAssertTrue(viewModel.canPresentLockConfirmation)
        XCTAssertNil(viewModel.taskValidationMessage)
    }

    func testTranscriptExtractionFailureKeepsManualTextFallbackRecoverable() async {
        struct ThrowingExtractor: VoiceDraftExtracting {
            var providerName: String { "Throwing" }

            func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
                _ = context
                throw VoiceDraftExtractionError.modelUnavailable
            }
        }

        let viewModel = makeViewModel(voiceDraftExtractor: ThrowingExtractor())
        viewModel.selectedInputMode = .voice

        await viewModel.extractTasksFromTranscript("Write launch email.")

        XCTAssertEqual(viewModel.selectedInputMode, .text)
        XCTAssertNil(viewModel.voiceDraft)
        XCTAssertEqual(viewModel.plan.source, .text)
        XCTAssertFalse(viewModel.plan.isLocked)
        XCTAssertEqual(viewModel.plan.tasks.map(\.text), ["", "", ""])
        XCTAssertTrue(viewModel.extractionStatus.localizedCaseInsensitiveContains("type instead"))
    }

    func testNoTasksExtractedShowsSpecificValidationMessage() async {
        struct EmptyExtractor: VoiceDraftExtracting {
            var providerName: String { "Empty" }

            func applyTranscript(_ context: VoiceDraftExtractionContext) async throws -> (VoiceDraftExtractionOutcome, VoiceDraftSessionState) {
                _ = context
                throw VoiceDraftExtractionError.emptyModelOutput
            }
        }

        let viewModel = makeViewModel(voiceDraftExtractor: EmptyExtractor())
        viewModel.selectedInputMode = .voice

        await viewModel.extractTasksFromTranscript("Hello? Testing, testing.")

        XCTAssertEqual(viewModel.selectedInputMode, .text)
        XCTAssertEqual(viewModel.taskValidationMessage, "No tasks extracted from transcript.")
        XCTAssertTrue(viewModel.extractionStatus.localizedCaseInsensitiveContains("No tasks extracted"))
    }

    func testMockVoiceFixturesAreValidExtractionEvalCases() {
        for fixture in MockVoiceDraftProvider.fixtures {
            let draft = fixture.draft
            let allCandidates = draft.selectedTasks + draft.extraCandidates

            XCTAssertFalse(fixture.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, fixture.title)
            XCTAssertLessThanOrEqual(draft.selectedTasks.count, 3, fixture.title)
            XCTAssertTrue(allCandidates.allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }, fixture.title)
            XCTAssertTrue(allCandidates.allSatisfy { $0.count <= 100 }, fixture.title)
            XCTAssertEqual(
                Set(allCandidates.map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }).count,
                allCandidates.count,
                fixture.title
            )
        }
    }

    func testEmptyTranscriptDoesNotCallExtractor() async {
        let viewModel = makeViewModel()

        await viewModel.extractTasksFromTranscript("   ")

        XCTAssertNil(viewModel.voiceDraft)
        XCTAssertTrue(viewModel.extractionStatus.localizedCaseInsensitiveContains("transcript"))
    }

    private func makeViewModel(
        voiceDraftExtractor: any VoiceDraftExtracting = HeuristicToolVoiceDraftExtractor(),
        dateProvider: @escaping () -> Date = Date.init
    ) -> AppViewModel {
        AppViewModel(defaults: defaults, voiceDraftExtractor: voiceDraftExtractor, dateProvider: dateProvider)
    }

    private var testCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .autoupdatingCurrent
        return calendar
    }

    private func localDate(year: Int, month: Int, day: Int, hour: Int, minute: Int = 0) -> Date {
        var components = DateComponents()
        components.calendar = testCalendar
        components.timeZone = .autoupdatingCurrent
        components.year = year
        components.month = month
        components.day = day
        components.hour = hour
        components.minute = minute
        components.second = 0
        return testCalendar.date(from: components)!
    }
}
