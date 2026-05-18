import Foundation

@MainActor
final class AppViewModel: ObservableObject {
    @Published var plan: DailyPlan
    @Published var selectedInputMode: InputMode = .voice
    @Published var pendingFinalizationDayID: String?
    @Published var momentum7: Int = 0
    @Published var extractionStatus: String = ""
    @Published var isExtracting: Bool = false
    @Published var voiceDraft: VoiceExtractionDraft?
    @Published var selectedVoiceFixtureID: String = MockVoiceDraftProvider.fixtures[2].id
    /// Latest transcript text from the live voice capture path (for resync and debugging).
    @Published private(set) var lastHeardTranscript: String = ""
    /// True after the user edits tasks/extras while a voice draft exists; live auto-extraction pauses until a new recording or explicit resync.
    @Published private(set) var userHasCustomizedVoicePlan: Bool = false
    /// True while the speech capture pipeline is actively recording.
    @Published private(set) var isVoiceRecordingActive: Bool = false
    /// Bumped when the root `ScrollView` should scroll to the top (e.g. replace-extra picker).
    @Published private(set) var scrollRootToTopToken: UInt = 0

    private struct StoredState: Codable {
        var plan: DailyPlan?
        var momentumOutcomes: [String: Bool]
        var lastFinalizedFocusDayID: String?
        var pendingFinalizationDayID: String?
    }

    private let storageKey = "three_things.v1.state"
    private let defaults: UserDefaults
    private let voiceDraftExtractor: any VoiceDraftExtracting
    private let mockVoiceDraftProvider: MockVoiceDraftProvider
    private let dateProvider: () -> Date
    private let liveExtractionDebounceNanoseconds: UInt64

    private var momentumOutcomes: [String: Bool] = [:]
    private var lastFinalizedFocusDayID: String?

    private var lastLiveExtractionSource: String?
    private var liveScheduler: LiveExtractionScheduler

    init(
        defaults: UserDefaults = .standard,
        voiceDraftExtractor: (any VoiceDraftExtracting)? = nil,
        mockVoiceDraftProvider: MockVoiceDraftProvider = MockVoiceDraftProvider(),
        dateProvider: @escaping () -> Date = Date.init,
        liveExtractionDebounceNanoseconds: UInt64 = 900_000_000
    ) {
        self.defaults = defaults
        self.voiceDraftExtractor = voiceDraftExtractor ?? AppVoiceDraftExtractorFactory.default()
        self.mockVoiceDraftProvider = mockVoiceDraftProvider
        self.dateProvider = dateProvider
        self.liveExtractionDebounceNanoseconds = liveExtractionDebounceNanoseconds
        self.plan = DailyPlan.empty(for: FocusDay.id(for: dateProvider()))
        self.liveScheduler = LiveExtractionScheduler(
            configuration: LiveExtractionScheduler.Configuration(
                debounceNanoseconds: liveExtractionDebounceNanoseconds
            ),
            canExtract: { false },
            onCustomizedWhileLive: {},
            handleRound: { _ in }
        )

        loadState()
        bootstrapForCurrentFocusDay()
        recomputeMomentum()
        saveState()

        installLiveScheduler()
    }

    private func installLiveScheduler() {
        liveScheduler = LiveExtractionScheduler(
            configuration: LiveExtractionScheduler.Configuration(
                debounceNanoseconds: liveExtractionDebounceNanoseconds
            ),
            canExtract: { [weak self] in
                self?.canScheduleLiveExtraction ?? false
            },
            onCustomizedWhileLive: { [weak self] in
                self?.notifyCustomizedWhileLive()
            },
            handleRound: { [weak self] round in
                await self?.handleLiveExtractionRound(round)
            }
        )
    }

    private var canScheduleLiveExtraction: Bool {
        canEditPlan && selectedInputMode == .voice && !userHasCustomizedVoicePlan
    }

    private func notifyCustomizedWhileLive() {
        if extractionStatus.isEmpty || extractionStatus.contains("Manual edits") {
            extractionStatus = "Manual edits kept—use “Apply latest voice” to resync."
        }
    }

    var progressText: String {
        if plan.isLocked {
            return "\(completedTaskCount)/\(lockedTaskCount) done"
        }
        return "\(draftTaskCount)/3 selected"
    }

    var completedTaskCount: Int {
        plan.tasks.filter { $0.isCompleted }.count
    }

    var draftTaskCount: Int {
        plan.tasks.reduce(into: 0) { count, item in
            if !normalized(item.text).isEmpty {
                count += 1
            }
        }
    }

    var lockedTaskCount: Int {
        max(plan.tasks.count, 1)
    }

    var duplicateTaskIndexes: Set<Int> {
        var firstIndexByText: [String: Int] = [:]
        var duplicates = Set<Int>()

        for (index, item) in plan.tasks.enumerated() {
            let key = duplicateKey(for: item.text)
            guard !key.isEmpty else { continue }

            if let firstIndex = firstIndexByText[key] {
                duplicates.insert(firstIndex)
                duplicates.insert(index)
            } else {
                firstIndexByText[key] = index
            }
        }

        return duplicates
    }

    var taskValidationMessage: String? {
        guard !plan.isLocked else { return nil }

        let nonEmptyCount = draftTaskCount
        if nonEmptyCount == 0 {
            if extractionStatus.localizedCaseInsensitiveContains("No tasks extracted") {
                return "No tasks extracted from transcript."
            }
            return "Choose at least 1 thing."
        }

        if nonEmptyCount > 3 {
            return "Choose no more than 3 things."
        }

        if !plan.extras.isEmpty {
            return "Resolve or discard extras before locking."
        }

        if plan.tasks.contains(where: { normalized($0.text).count > 100 }) {
            return "Each thing must be 100 characters or fewer."
        }

        if !duplicateTaskIndexes.isEmpty {
            return "Each thing needs to be distinct."
        }

        return nil
    }

    var canLockPlan: Bool {
        canPresentLockConfirmation
    }

    var canPresentLockConfirmation: Bool {
        guard !plan.isLocked else { return false }

        let nonEmptyCount = draftTaskCount
        guard (1...3).contains(nonEmptyCount) else { return false }
        guard plan.extras.isEmpty else { return false }

        guard plan.tasks.allSatisfy({ item in
            let text = normalized(item.text)
            return text.count <= 100
        }) else { return false }

        return duplicateTaskIndexes.isEmpty
    }

    var canEditPlan: Bool {
        !plan.isLocked
    }

    var voiceFixtures: [MockVoiceDraftFixture] {
        MockVoiceDraftProvider.fixtures
    }

    var selectedVoiceFixture: MockVoiceDraftFixture {
        mockVoiceDraftProvider.fixture(withID: selectedVoiceFixtureID)
    }

    func characterCount(at index: Int) -> Int {
        guard plan.tasks.indices.contains(index) else { return 0 }
        return normalized(plan.tasks[index].text).count
    }

    /// Scroll the root screen to the top (used when presenting UI anchored to the top, e.g. replace-extra picker).
    func requestScrollRootToTop() {
        scrollRootToTopToken &+= 1
    }

    func updateTaskText(at index: Int, text: String) {
        guard canEditPlan, plan.tasks.indices.contains(index) else { return }

        let clamped = String(text.prefix(100))
        plan.tasks[index].text = clamped
        if voiceDraft != nil {
            userHasCustomizedVoicePlan = true
        }
        syncVoiceDraftFromPlan()
        recomputeMomentum()
        saveState()
    }

    func moveTask(from sourceIndex: Int, to destinationIndex: Int) {
        guard canEditPlan,
              plan.tasks.indices.contains(sourceIndex),
              plan.tasks.indices.contains(destinationIndex),
              sourceIndex != destinationIndex else {
            return
        }

        let item = plan.tasks.remove(at: sourceIndex)
        plan.tasks.insert(item, at: destinationIndex)
        normalizeDraftSortOrder()
        if voiceDraft != nil {
            userHasCustomizedVoicePlan = true
        }
        syncVoiceDraftFromPlan()
        saveState()
    }

    func confirmLockPlan() {
        guard canPresentLockConfirmation else { return }

        let lockedTasks = plan.tasks
            .map { item -> TaskItem in
                var nextItem = item
                nextItem.text = normalized(nextItem.text)
                nextItem.isCompleted = false
                return nextItem
            }
            .filter { !$0.text.isEmpty }
            .prefix(3)
            .enumerated()
            .map { index, item in
                var nextItem = item
                nextItem.sortOrder = index
                return nextItem
            }

        plan.tasks = Array(lockedTasks)

        if voiceDraft == nil {
            plan.source = .text
        }
        plan.isLocked = true
        recomputeMomentum()
        saveState()
    }

    func toggleCompletion(taskID: UUID) {
        guard plan.isLocked,
              let index = plan.tasks.firstIndex(where: { $0.id == taskID }) else {
            return
        }

        plan.tasks[index].isCompleted.toggle()
        recomputeMomentum()
        saveState()
    }

    func finalizePendingDay(completed: Bool) {
        guard let pendingID = pendingFinalizationDayID else { return }

        momentumOutcomes[pendingID] = completed
        lastFinalizedFocusDayID = pendingID
        pendingFinalizationDayID = nil

        recomputeMomentum()
        saveState()
    }

    func startVoiceDraftReview(from draft: VoiceExtractionDraft) {
        guard canEditPlan else { return }

        let normalizedSelected = cappedTasks(from: draft.selectedTasks, fillToThree: true)
        let normalizedExtras = cappedTasks(from: draft.extraCandidates, fillToThree: false)
        let nextDraft = VoiceExtractionDraft(
            selectedTasks: Array(normalizedSelected.prefix(3)),
            extraCandidates: normalizedExtras,
            detectedMoreThanThree: draft.detectedMoreThanThree || !normalizedExtras.isEmpty,
            cleanedTranscript: normalized(draft.cleanedTranscript)
        )

        voiceDraft = nextDraft
        plan.source = .voice
        plan.extras = nextDraft.extraCandidates
        plan.detectedMoreThanThree = nextDraft.detectedMoreThanThree
        userHasCustomizedVoicePlan = false

        for index in plan.tasks.indices {
            plan.tasks[index].text = index < normalizedSelected.count ? normalizedSelected[index] : ""
            plan.tasks[index].isCompleted = false
            plan.tasks[index].sortOrder = index
        }

        selectedInputMode = .voice
        recomputeMomentum()
        saveState()
    }

    func generateMockVoiceDraft() {
        let fixture = selectedVoiceFixture
        startVoiceDraftReview(from: fixture.draft)
        extractionStatus = "Drafted from \(fixture.title)."
    }

    func replaceSelectedTask(at selectedIndex: Int, withExtraAt extraIndex: Int) {
        guard canEditPlan,
              plan.tasks.indices.contains(selectedIndex),
              plan.extras.indices.contains(extraIndex) else {
            return
        }

        let extra = plan.extras.remove(at: extraIndex)
        let currentText = normalized(plan.tasks[selectedIndex].text)
        plan.tasks[selectedIndex].text = extra
        if !currentText.isEmpty {
            plan.extras.append(currentText)
        }
        if voiceDraft != nil {
            userHasCustomizedVoicePlan = true
        }
        syncVoiceDraftFromPlan()
        saveState()
    }

    func updateExtraCandidate(at index: Int, text: String) {
        guard canEditPlan, plan.extras.indices.contains(index) else { return }

        plan.extras[index] = normalized(String(text.prefix(100)))
        if voiceDraft != nil {
            userHasCustomizedVoicePlan = true
        }
        syncVoiceDraftFromPlan()
        saveState()
    }

    func discardExtraCandidate(at index: Int) {
        guard canEditPlan, plan.extras.indices.contains(index) else { return }

        plan.extras.remove(at: index)
        if voiceDraft != nil {
            userHasCustomizedVoicePlan = true
        }
        syncVoiceDraftFromPlan()
        saveState()
    }

    func returnToTextEntry() {
        guard canEditPlan else { return }

        liveScheduler.cancelPending()
        userHasCustomizedVoicePlan = false
        lastHeardTranscript = ""
        liveScheduler.resetForNewRecording()

        voiceDraft = nil
        plan = DailyPlan.empty(for: plan.focusDayID)
        selectedInputMode = .text
        extractionStatus = ""
        recomputeMomentum()
        saveState()
    }

    func switchToVoiceFromText() {
        guard canEditPlan else { return }
        liveScheduler.sessionState = nil
        selectedInputMode = .voice
        saveState()
    }

    func resetVoiceCustomizationForNewRecording() {
        userHasCustomizedVoicePlan = false
        lastLiveExtractionSource = nil
        extractionStatus = ""
        liveScheduler.cancelPending()
        liveScheduler.resetForNewRecording()
    }

    func setVoiceRecordingActive(_ active: Bool) {
        isVoiceRecordingActive = active
    }

    func updateVoiceTranscriptSnapshot(_ transcript: String) {
        let clean = VoiceDraftSessionLogic.normalize(transcript)
        lastHeardTranscript = clean
        liveScheduler.ingestPartial(transcript)
    }

    /// Runs extraction immediately (e.g. after stop recording) without waiting for debounce.
    func ingestFinalTranscript(_ transcript: String) async {
        let clean = VoiceDraftSessionLogic.normalize(transcript)
        lastHeardTranscript = clean
        await liveScheduler.ingestFinal(transcript)
    }

    func flushLiveExtractionNow(transcript: String) async {
        await ingestFinalTranscript(transcript)
    }

    func applyLatestVoiceResync() async {
        guard canEditPlan else { return }
        userHasCustomizedVoicePlan = false
        liveScheduler.cancelPending()
        liveScheduler.resetForNewRecording()
        let fromLive = normalized(lastHeardTranscript)
        let fromDraft = normalized(voiceDraft?.cleanedTranscript ?? "")
        let text = fromLive.isEmpty ? fromDraft : fromLive
        guard !text.isEmpty else {
            extractionStatus = "No transcript to resync."
            return
        }
        await ingestFinalTranscript(text)
    }

    func resetExtractionStatus() {
        extractionStatus = ""
    }

    func extractTasksFromTranscript(_ transcript: String, isLive: Bool = false, userFinishedSpeaking: Bool = false) async {
        guard !isLive else {
            let clean = VoiceDraftSessionLogic.normalize(transcript)
            lastHeardTranscript = clean
            if userFinishedSpeaking {
                await ingestFinalTranscript(transcript)
            } else {
                updateVoiceTranscriptSnapshot(transcript)
            }
            return
        }

        guard canEditPlan else {
            extractionStatus = "Tasks are already locked for today."
            return
        }

        let cleanTranscript = normalized(transcript)
        guard !cleanTranscript.isEmpty else {
            extractionStatus = "Add or record transcript text first."
            return
        }

        let snapshot = TranscriptSnapshot(fullText: cleanTranscript, isFinal: userFinishedSpeaking)
        let request = VoiceDraftSessionLogic.buildRequest(snapshot: snapshot, session: nil)
        await runExtractionRound(
            request: request,
            snapshot: snapshot,
            isLive: false,
            userFinishedSpeaking: userFinishedSpeaking
        )
    }

    private func handleLiveExtractionRound(_ round: LiveExtractionRound) async {
        switch round {
        case .clientSkip(let outcome, let newState, let request, let snapshot):
            guard isSnapshotStillCurrent(snapshot) else { return }
            liveScheduler.sessionState = newState
            applyExtractionOutcome(
                outcome,
                cleanTranscript: request.fullTranscript,
                isLive: true,
                userFinishedSpeaking: request.userFinishedSpeaking
            )
            recomputeMomentum()
            saveState()

        case .model(let request, let snapshot):
            await runExtractionRound(
                request: request,
                snapshot: snapshot,
                isLive: true,
                userFinishedSpeaking: request.userFinishedSpeaking
            )
        }
    }

    private func runExtractionRound(
        request: ExtractionRequest,
        snapshot: TranscriptSnapshot,
        isLive: Bool,
        userFinishedSpeaking: Bool
    ) async {
        guard canEditPlan else {
            extractionStatus = "Tasks are already locked for today."
            return
        }

        if isLive, userHasCustomizedVoicePlan {
            return
        }

        let cleanTranscript = request.fullTranscript
        guard !cleanTranscript.isEmpty else {
            extractionStatus = "Add or record transcript text first."
            return
        }

        isExtracting = true
        defer { isExtracting = false }

        do {
            let (outcome, newState) = try await voiceDraftExtractor.applyTranscript(request.extractionContext)

            if isLive, !isSnapshotStillCurrent(snapshot) {
                extractionStatus = "You kept talking—that draft was skipped; matching your latest words next."
                if let latest = liveScheduler.latestSnapshot {
                    if latest.isFinal {
                        await ingestFinalTranscript(latest.fullText)
                    } else {
                        updateVoiceTranscriptSnapshot(latest.fullText)
                    }
                }
                return
            }

            liveScheduler.sessionState = newState

            applyExtractionOutcome(
                outcome,
                cleanTranscript: cleanTranscript,
                isLive: isLive,
                userFinishedSpeaking: userFinishedSpeaking
            )
        } catch {
            if isLive, !isSnapshotStillCurrent(snapshot) {
                extractionStatus = "Transcript changed while extracting—we'll try again with what you said last."
                if let latest = liveScheduler.latestSnapshot {
                    if latest.isFinal {
                        await ingestFinalTranscript(latest.fullText)
                    } else {
                        updateVoiceTranscriptSnapshot(latest.fullText)
                    }
                }
                return
            }
            if isLive {
                extractionStatus = error.localizedDescription
            } else {
                voiceDraft = nil
                liveScheduler.sessionState = nil
                plan = DailyPlan.empty(for: plan.focusDayID)
                selectedInputMode = .text
                extractionStatus = "\(error.localizedDescription) Type instead."
            }
        }

        recomputeMomentum()
        saveState()
    }

    private func isSnapshotStillCurrent(_ snapshot: TranscriptSnapshot) -> Bool {
        VoiceDraftSessionLogic.normalize(snapshot.fullText)
            == VoiceDraftSessionLogic.normalize(liveScheduler.latestSnapshot?.fullText ?? "")
    }

    private func applyExtractionOutcome(
        _ outcome: VoiceDraftExtractionOutcome,
        cleanTranscript: String,
        isLive: Bool,
        userFinishedSpeaking: Bool
    ) {
        switch outcome {
        case .draft(let draft):
            startVoiceDraftReview(from: draft)
            lastLiveExtractionSource = cleanTranscript
            extractionStatus = isLive
                ? "Updated from voice (\(voiceDraftExtractor.providerName))."
                : "Drafted tasks from \(voiceDraftExtractor.providerName). Review and lock."

        case .noDraft(let reason):
            switch reason {
            case .incomplete:
                if isLive {
                    extractionStatus = ""
                } else if userFinishedSpeaking {
                    if !hasVisibleVoiceDraftContent() {
                        clearVoiceCaptureDraftForNoTasks()
                        extractionStatus = "No tasks extracted from transcript."
                    } else {
                        extractionStatus = ""
                    }
                } else {
                    extractionStatus = ""
                }

            case .noActionable:
                if !hasVisibleVoiceDraftContent() {
                    clearVoiceCaptureDraftForNoTasks()
                }
                extractionStatus = (!isLive || userFinishedSpeaking) && !hasVisibleVoiceDraftContent()
                    ? "No tasks extracted from transcript."
                    : ""

            case .unchanged:
                extractionStatus = ""
            }
        }
    }

    private func hasVisibleVoiceDraftContent() -> Bool {
        voiceDraft != nil || plan.tasks.contains { !normalized($0.text).isEmpty }
    }

    private func clearVoiceCaptureDraftForNoTasks() {
        voiceDraft = nil
        plan.source = .voice
        plan.extras = []
        plan.detectedMoreThanThree = false
        for index in plan.tasks.indices {
            plan.tasks[index].text = ""
            plan.tasks[index].isCompleted = false
            plan.tasks[index].sortOrder = index
        }
    }

    private func bootstrapForCurrentFocusDay() {
        let currentFocusDayID = FocusDay.id(for: dateProvider())

        if plan.focusDayID != currentFocusDayID {
            handleFocusDayRollover(from: plan)
            plan = DailyPlan.empty(for: currentFocusDayID)
            selectedInputMode = .voice
            voiceDraft = nil
        }

        pruneMomentumWindow()
    }

    private func handleFocusDayRollover(from previousPlan: DailyPlan) {
        guard previousPlan.isLocked else { return }

        if !previousPlan.tasks.isEmpty && previousPlan.tasks.allSatisfy({ $0.isCompleted }) {
            momentumOutcomes[previousPlan.focusDayID] = true
            lastFinalizedFocusDayID = previousPlan.focusDayID
        } else if pendingFinalizationDayID == nil {
            pendingFinalizationDayID = previousPlan.focusDayID
        }
    }

    private func pruneMomentumWindow() {
        let validIDs = Set(FocusDay.trailingIDs(count: 7, endingAt: dateProvider()))
        momentumOutcomes = momentumOutcomes.filter { validIDs.contains($0.key) }
    }

    private func recomputeMomentum() {
        let trailingIDs = FocusDay.trailingIDs(count: 7, endingAt: dateProvider())

        momentum7 = trailingIDs.reduce(into: 0) { count, focusDayID in
            if focusDayID == plan.focusDayID,
               plan.isLocked,
               !plan.tasks.isEmpty,
               plan.tasks.allSatisfy({ $0.isCompleted }) {
                count += 1
                return
            }

            if momentumOutcomes[focusDayID] == true {
                count += 1
            }
        }
    }

    private func loadState() {
        guard let data = defaults.data(forKey: storageKey),
              let state = try? JSONDecoder().decode(StoredState.self, from: data) else {
            return
        }

        if let storedPlan = state.plan {
            plan = storedPlan
        }

        momentumOutcomes = state.momentumOutcomes
        lastFinalizedFocusDayID = state.lastFinalizedFocusDayID
        pendingFinalizationDayID = state.pendingFinalizationDayID
    }

    private func saveState() {
        let state = StoredState(
            plan: plan,
            momentumOutcomes: momentumOutcomes,
            lastFinalizedFocusDayID: lastFinalizedFocusDayID,
            pendingFinalizationDayID: pendingFinalizationDayID
        )

        guard let data = try? JSONEncoder().encode(state) else { return }
        defaults.set(data, forKey: storageKey)
    }

    private func normalized(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func duplicateKey(for value: String) -> String {
        normalized(value).lowercased()
    }

    private func normalizeDraftSortOrder() {
        for index in plan.tasks.indices {
            plan.tasks[index].sortOrder = index
        }
    }

    private func cappedTasks(from values: [String], fillToThree: Bool) -> [String] {
        var tasks = values
            .map { normalized(String($0.prefix(100))) }
            .filter { !$0.isEmpty }

        if fillToThree {
            tasks = Array(tasks.prefix(3))
            while tasks.count < 3 {
                tasks.append("")
            }
        }

        return tasks
    }

    private func syncVoiceDraftFromPlan() {
        guard let voiceDraft else { return }

        self.voiceDraft = VoiceExtractionDraft(
            selectedTasks: plan.tasks.map(\.text).filter { !normalized($0).isEmpty },
            extraCandidates: plan.extras,
            detectedMoreThanThree: !plan.extras.isEmpty || plan.detectedMoreThanThree,
            cleanedTranscript: voiceDraft.cleanedTranscript
        )
        plan.detectedMoreThanThree = self.voiceDraft?.detectedMoreThanThree ?? false
    }
}
