import XCTest
@testable import ThreeThings

final class VoiceDraftPostProcessorTests: XCTestCase {
    func testExtrasForceOverflowFlag() throws {
        let draft = try VoiceDraftPostProcessor.buildDraft(
            selectedTasks: ["A", "B", "C"],
            extraCandidates: ["D"],
            detectedMoreThanThree: false,
            cleanedTranscript: "A B C D"
        )
        XCTAssertTrue(draft.detectedMoreThanThree)
        XCTAssertEqual(draft.extraCandidates, ["D"])
    }

    func testLongCandidatesClampToOneHundred() throws {
        let longA = String(repeating: "a", count: 140)
        let longB = String(repeating: "b", count: 140)
        let longC = String(repeating: "c", count: 140)
        let longOverflow = String(repeating: "d", count: 140)
        let draft = try VoiceDraftPostProcessor.buildDraft(
            selectedTasks: [longA, longB, longC, longOverflow],
            extraCandidates: [],
            detectedMoreThanThree: true,
            cleanedTranscript: "x"
        )
        XCTAssertEqual(draft.selectedTasks.count, 3)
        XCTAssertEqual(draft.selectedTasks[0].count, 100)
        XCTAssertEqual(draft.selectedTasks[1].count, 100)
        XCTAssertEqual(draft.selectedTasks[2].count, 100)
        XCTAssertEqual(draft.extraCandidates.count, 1)
        XCTAssertEqual(draft.extraCandidates[0].count, 100)
    }

    func testDuplicateSelectedTasksAreDeduplicated() throws {
        let draft = try VoiceDraftPostProcessor.buildDraft(
            selectedTasks: ["Ship app", "ship app", "Write docs"],
            extraCandidates: [],
            detectedMoreThanThree: false,
            cleanedTranscript: "Ship app write docs"
        )
        XCTAssertEqual(draft.selectedTasks, ["Ship app", "Write docs"])
    }

    func testEmptySelectedThrows() {
        XCTAssertThrowsError(
            try VoiceDraftPostProcessor.buildDraft(
                selectedTasks: ["", "  "],
                extraCandidates: [],
                detectedMoreThanThree: false,
                cleanedTranscript: "x"
            )
        ) { error in
            XCTAssertEqual(error as? VoiceDraftExtractionError, .emptyModelOutput)
        }
    }

    func testNoActionableTasksThrowsEvenWhenModelInventsTasks() {
        XCTAssertThrowsError(
            try VoiceDraftPostProcessor.buildDraft(
                selectedTasks: ["Prepare for meeting", "Review emails", "Call client"],
                extraCandidates: ["Organize workspace", "Set reminders"],
                detectedMoreThanThree: true,
                containsActionableTasks: false,
                cleanedTranscript: "Hello? Testing, testing."
            )
        ) { error in
            XCTAssertEqual(error as? VoiceDraftExtractionError, .emptyModelOutput)
        }
    }
}
