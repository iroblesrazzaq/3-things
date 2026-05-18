import Foundation

// MARK: - Report types (Codable for JSON export)

struct VoiceExtractionEvalRunOutcome: Codable, Equatable, Sendable {
    var passed: Bool
    var reasons: [String]
    var selectedTasks: [String]
    var extraCandidates: [String]
    var detectedMoreThanThree: Bool
    var errorDescription: String?
}

struct VoiceExtractionEvalVariantReport: Codable, Equatable, Sendable {
    var caseId: String
    var category: String
    var transcriptIndex: Int
    var transcript: String
    var runs: [VoiceExtractionEvalRunOutcome]
    var passRate: Double
    var firstPass: Bool
    var hallucinationRunCount: Int
}

struct VoiceExtractionEvalCategorySummary: Codable, Equatable, Sendable {
    var category: String
    var variantCount: Int
    var meanPassRate: Double
    var firstPassRate: Double
    var totalHallucinationRuns: Int
}

struct VoiceExtractionEvalReport: Codable, Equatable, Sendable {
    var generatedAt: Date
    var runsPerTranscript: Int
    var variants: [VoiceExtractionEvalVariantReport]
    var categorySummaries: [VoiceExtractionEvalCategorySummary]
    var meanPassRateAcrossVariants: Double
    var firstPassRateAcrossVariants: Double
    var totalVariants: Int
}

extension VoiceExtractionEvalReport {
    func writeJSON(to url: URL) throws {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        enc.dateEncodingStrategy = .iso8601
        try enc.encode(self).write(to: url, options: .atomic)
    }
}

// MARK: - Runner

/// Runs `FoundationModelsVoiceDraftExtractor` repeatedly per transcript. Use on a physical device with Apple Intelligence available.
enum VoiceExtractionEvalRunner {
    private static let hallucinationCodes: Set<String> = [
        VoiceExtractionEvalFailureReason.inventedSelected.rawValue,
        VoiceExtractionEvalFailureReason.inventedExtra.rawValue,
        VoiceExtractionEvalFailureReason.overSpecificRewrite.rawValue,
        VoiceExtractionEvalFailureReason.noTaskFalsePositive.rawValue,
    ]

    static func run(
        cases: [VoiceExtractionEvalCase],
        runsPerTranscript: Int = 5,
        extractor: ToolVoiceDraftExtractor = ToolVoiceDraftExtractor(),
        progress: (@MainActor (String) -> Void)? = nil
    ) async -> VoiceExtractionEvalReport {
        let n = max(1, runsPerTranscript)
        var variants: [VoiceExtractionEvalVariantReport] = []

        for evalCase in cases {
            for (ti, transcript) in evalCase.transcriptVariants.enumerated() {
                await MainActor.run {
                    progress?("\(evalCase.id) #\(ti + 1)")
                }
                var outcomes: [VoiceExtractionEvalRunOutcome] = []

                for _ in 0..<n {
                    outcomes.append(await singleRun(evalCase: evalCase, transcript: transcript, extractor: extractor))
                }

                let passes = outcomes.filter(\.passed).count
                let passRate = Double(passes) / Double(n)
                let firstPass = outcomes.first?.passed ?? false
                let hallRuns = outcomes.filter { $0.reasons.contains { hallucinationCodes.contains($0) } }.count

                variants.append(
                    VoiceExtractionEvalVariantReport(
                        caseId: evalCase.id,
                        category: evalCase.category,
                        transcriptIndex: ti,
                        transcript: transcript,
                        runs: outcomes,
                        passRate: passRate,
                        firstPass: firstPass,
                        hallucinationRunCount: hallRuns
                    )
                )
            }
        }

        let categories = Set(variants.map(\.category))
        let summaries: [VoiceExtractionEvalCategorySummary] = categories.sorted().map { cat in
            let vs = variants.filter { $0.category == cat }
            let meanPR = vs.isEmpty ? 0 : vs.map(\.passRate).reduce(0, +) / Double(vs.count)
            let firstPassN = vs.filter(\.firstPass).count
            let hall = vs.map(\.hallucinationRunCount).reduce(0, +)
            return VoiceExtractionEvalCategorySummary(
                category: cat,
                variantCount: vs.count,
                meanPassRate: meanPR,
                firstPassRate: vs.isEmpty ? 0 : Double(firstPassN) / Double(vs.count),
                totalHallucinationRuns: hall
            )
        }

        let meanOverall = variants.isEmpty ? 0 : variants.map(\.passRate).reduce(0, +) / Double(variants.count)
        let firstOverall = variants.isEmpty ? 0 : Double(variants.filter(\.firstPass).count) / Double(variants.count)

        return VoiceExtractionEvalReport(
            generatedAt: Date(),
            runsPerTranscript: n,
            variants: variants,
            categorySummaries: summaries,
            meanPassRateAcrossVariants: meanOverall,
            firstPassRateAcrossVariants: firstOverall,
            totalVariants: variants.count
        )
    }

    private static func singleRun(
        evalCase: VoiceExtractionEvalCase,
        transcript: String,
        extractor: ToolVoiceDraftExtractor
    ) async -> VoiceExtractionEvalRunOutcome {
        var draft: VoiceExtractionDraft?
        var err: Error?
        do {
            draft = try await extractor.extractDraft(from: transcript)
        } catch {
            err = error
            draft = nil
        }
        let score = VoiceExtractionEvalScorer.score(evalCase: evalCase, draft: draft, extractionError: err)
        let d = draft
        return VoiceExtractionEvalRunOutcome(
            passed: score.passed,
            reasons: score.reasons.map(\.rawValue),
            selectedTasks: d?.selectedTasks ?? [],
            extraCandidates: d?.extraCandidates ?? [],
            detectedMoreThanThree: d?.detectedMoreThanThree ?? false,
            errorDescription: err.map { String(describing: $0) }
        )
    }
}
