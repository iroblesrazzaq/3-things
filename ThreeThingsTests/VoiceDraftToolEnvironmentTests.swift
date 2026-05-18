import XCTest
@testable import ThreeThings

final class VoiceDraftToolEnvironmentTests: XCTestCase {
    func testAddTaskFillsSelectedThenExtras() {
        let env = VoiceDraftToolEnvironment(copying: nil)
        _ = env.addTask(text: "A")
        _ = env.addTask(text: "B")
        _ = env.addTask(text: "C")
        _ = env.addTask(text: "D")
        XCTAssertEqual(env.selectedTasks, ["A", "B", "C"])
        XCTAssertEqual(env.extraCandidates, ["D"])
    }

    func testDeleteSelectedShifts() {
        let env = VoiceDraftToolEnvironment(copying: nil)
        _ = env.addTask(text: "A")
        _ = env.addTask(text: "B")
        _ = env.deleteTask(pool: .selected, slot: 0)
        XCTAssertEqual(env.selectedTasks, ["B"])
    }

    func testReviseExtra() {
        let env = VoiceDraftToolEnvironment(copying: nil)
        _ = env.addTask(text: "A")
        _ = env.addTask(text: "B")
        _ = env.addTask(text: "C")
        _ = env.addTask(text: "D")
        _ = env.reviseTask(pool: .extra, slot: 0, newText: "D2")
        XCTAssertEqual(env.extraCandidates, ["D2"])
    }

    func testClearDraft() {
        let env = VoiceDraftToolEnvironment(copying: nil)
        _ = env.addTask(text: "X")
        _ = env.clearDraft()
        XCTAssertTrue(env.selectedTasks.isEmpty)
        XCTAssertTrue(env.extraCandidates.isEmpty)
    }

    func testNormalizeToDraftRecomputesOverflow() throws {
        let env = VoiceDraftToolEnvironment(copying: nil)
        _ = env.addTask(text: "A")
        _ = env.addTask(text: "B")
        _ = env.addTask(text: "C")
        _ = env.addTask(text: "D")
        let draft = try env.normalizeToDraft(cleanedTranscript: "A B C D")
        XCTAssertTrue(draft.detectedMoreThanThree)
    }

    func testSemanticDuplicateAddSkipped() {
        let env = VoiceDraftToolEnvironment(copying: nil)
        _ = env.addTask(text: "email Sam")
        let msg = env.addTask(text: "send Sam an email")
        XCTAssertTrue(msg.localizedCaseInsensitiveContains("duplicate"))
        XCTAssertEqual(env.selectedTasks.count, 1)
    }

    func testRecordNoActionStoresReason() {
        let env = VoiceDraftToolEnvironment(copying: nil)
        env.recordNoAction(reason: .incomplete)
        XCTAssertEqual(env.lastNoActionReason, .incomplete)
        env.recordNoAction(reason: .noActionable)
        XCTAssertEqual(env.lastNoActionReason, .noActionable)
        env.recordNoAction(reason: .unchanged)
        XCTAssertEqual(env.lastNoActionReason, .unchanged)
    }

    func testAddTaskThenNoActionLeavesTasks() {
        let env = VoiceDraftToolEnvironment(copying: nil)
        _ = env.addTask(text: "call mom")
        env.recordNoAction(reason: .unchanged)
        XCTAssertTrue(env.hasAnyTaskText())
        XCTAssertEqual(env.selectedTasks, ["call mom"])
    }
}
