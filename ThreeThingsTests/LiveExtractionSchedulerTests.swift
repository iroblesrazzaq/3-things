import XCTest
@testable import ThreeThings

@MainActor
final class LiveExtractionSchedulerTests: XCTestCase {
    func testDebounceFiresOnceAfterDelay() async throws {
        var rounds: [LiveExtractionRound] = []
        let scheduler = LiveExtractionScheduler(
            configuration: LiveExtractionScheduler.Configuration(debounceNanoseconds: 80_000_000),
            canExtract: { true },
            handleRound: { round in
                rounds.append(round)
            }
        )

        scheduler.ingestPartial("one, two, three, four, five, six, seven, eight")
        try await Task.sleep(nanoseconds: 200_000_000)

        XCTAssertEqual(rounds.count, 1)
        if case .model(let request, _) = rounds[0] {
            XCTAssertFalse(request.userFinishedSpeaking)
        } else {
            XCTFail("Expected model round")
        }
    }

    func testRapidPartialsCoalesceToLatest() async throws {
        var modelRounds = 0
        let scheduler = LiveExtractionScheduler(
            configuration: LiveExtractionScheduler.Configuration(debounceNanoseconds: 120_000_000),
            canExtract: { true },
            handleRound: { round in
                if case .model = round { modelRounds += 1 }
            }
        )

        scheduler.ingestPartial("alpha, beta, gamma, delta, epsilon, zeta, eta, theta")
        try await Task.sleep(nanoseconds: 50_000_000)
        scheduler.ingestPartial("one, two, three, four, five, six, seven, eight")
        try await Task.sleep(nanoseconds: 400_000_000)

        XCTAssertEqual(modelRounds, 1)
    }

    func testMinLiveCharactersBlocksDispatch() async throws {
        var rounds = 0
        let scheduler = LiveExtractionScheduler(
            configuration: LiveExtractionScheduler.Configuration(debounceNanoseconds: 50_000_000),
            canExtract: { true },
            handleRound: { _ in rounds += 1 }
        )

        scheduler.ingestPartial("short")
        try await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(rounds, 0)
    }

    func testIngestFinalSkipsDebounce() async throws {
        var finished = false
        let scheduler = LiveExtractionScheduler(
            canExtract: { true },
            handleRound: { round in
                if case .model(let request, let snapshot) = round {
                    finished = request.userFinishedSpeaking && snapshot.isFinal
                }
            }
        )

        await scheduler.ingestFinal("Hi.")
        XCTAssertTrue(finished)
    }

    func testDuplicateFinalWithinWindowDeduped() async throws {
        var count = 0
        let scheduler = LiveExtractionScheduler(
            configuration: LiveExtractionScheduler.Configuration(
                finalDedupWindowNanoseconds: 500_000_000
            ),
            canExtract: { true },
            handleRound: { _ in count += 1 }
        )

        await scheduler.ingestFinal("one, two, three, four, five, six, seven, eight")
        await scheduler.ingestFinal("one, two, three, four, five, six, seven, eight")
        XCTAssertEqual(count, 1)
    }

    func testSkipModelRoundWhenEmptyFragmentWhileRecording() async throws {
        let scheduler = LiveExtractionScheduler(
            canExtract: { true },
            handleRound: { _ in }
        )

        let transcript = "one, two, three, four, five, six, seven, eight"
        await scheduler.ingestFinal(transcript)
        scheduler.sessionState = VoiceDraftSessionState(
            selectedTasks: ["task"],
            processedTranscriptCharacterCount: transcript.count,
            lastFullTranscript: transcript
        )

        let snapshot = TranscriptSnapshot(fullText: transcript, isFinal: false)
        let request = VoiceDraftSessionLogic.buildRequest(
            snapshot: snapshot,
            session: scheduler.sessionState
        )
        XCTAssertTrue(request.newFragment.isEmpty)
        XCTAssertTrue(VoiceDraftSessionLogic.shouldSkipModelRound(request))

        let skipped = VoiceDraftSessionLogic.skippedOutcome(for: request)
        XCTAssertEqual(skipped.0, .noDraft(reason: .unchanged))
    }

    func testFragmentAfterProcessedIndex() {
        var session = VoiceDraftSessionState(
            selectedTasks: ["a"],
            processedTranscriptCharacterCount: 3,
            lastFullTranscript: "abc"
        )
        let full = "abcdef"
        let fragment = VoiceDraftSessionLogic.newTranscriptFragment(full: full, state: session)
        XCTAssertEqual(fragment, "def")

        session.processedTranscriptCharacterCount = full.count
        session.lastFullTranscript = full
        let fragment2 = VoiceDraftSessionLogic.newTranscriptFragment(full: full, state: session)
        XCTAssertEqual(fragment2, "")
    }

    func testSessionResetOnNonPrefix() {
        let existing = VoiceDraftSessionState(
            selectedTasks: ["old"],
            processedTranscriptCharacterCount: 10,
            lastFullTranscript: "completely different"
        )
        XCTAssertTrue(
            VoiceDraftSessionLogic.shouldResetVoiceDraftSession(
                existing: existing,
                full: "new transcript entirely"
            )
        )
    }

    func testLiveStepsFromSnapshots() {
        let snapshots = [
            "Go to the park",
            "Go to the park, wait never mind, go to the store.",
        ]
        let steps = VoiceDraftSessionLogic.liveSteps(from: snapshots)
        XCTAssertEqual(steps.count, 2)
        XCTAssertEqual(steps[0].fragment, "Go to the park")
        XCTAssertFalse(steps[0].finished)
        XCTAssertTrue(steps[1].finished)
        XCTAssertTrue(steps[1].fragment.contains("never mind"))
    }

    func testFixtureDiagnosticSnapshotsProduceSteps() throws {
        let bundle = Bundle(for: LiveExtractionSchedulerTests.self)
        let cases = try VoiceExtractionEvalLoader.loadCases(from: bundle)
        let diagnosticIDs: Set<String> = [
            "literal_three_store_park_food",
            "overflow_four_clean",
            "correction_never_mind_single",
            "no_task_testing",
            "inference_store_only",
            "duplicate_email_sam",
            "vague_taxes",
        ]
        let url = bundle.url(forResource: "voice_extraction_cases", withExtension: "json")
        XCTAssertNotNil(url)
        let data = try Data(contentsOf: url!)
        let raw = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let rawCases = raw["cases"] as! [[String: Any]]

        for rawCase in rawCases {
            guard let id = rawCase["id"] as? String, diagnosticIDs.contains(id) else { continue }
            let snapshots = rawCase["liveSnapshots"] as! [String]
            XCTAssertFalse(snapshots.isEmpty, id)
            let steps = VoiceDraftSessionLogic.liveSteps(from: snapshots)
            XCTAssertFalse(steps.isEmpty, id)
            XCTAssertTrue(steps.last!.finished, id)
        }
        XCTAssertEqual(cases.filter { diagnosticIDs.contains($0.id) }.count, 7)
    }
}
