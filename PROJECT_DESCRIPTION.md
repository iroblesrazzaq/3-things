# Project Description

## Goal

**3-things** is a native iOS app for radical daily focus. Each day, the user commits to **1 to 3 things that matter**, locks them for the current focus day, and executes without adding, carrying over, or constantly reshuffling tasks.

The product intentionally avoids becoming a general task manager. It is built around one daily commitment loop:

1. Capture today's 1-3 things.
2. Review and validate them.
3. Explicitly lock the plan.
4. Complete the locked tasks during the day.
5. Start fresh on the next focus day.

The MVP product direction is voice-first and local-first: speak messy thoughts, transcribe them on device, extract the 1-3 actionable tasks with Apple's on-device Foundation Models, edit them, then lock. Typing remains available as a fallback input mode, but the intended differentiator is private, zero-cost voice-to-task extraction.

## Implementation Details

### Platform And Stack

- Native iOS app.
- Swift 6.
- SwiftUI.
- MVVM-style app state centered around `AppViewModel`.
- Minimal persistence with `UserDefaults` and `Codable`.
- Modern Apple Intelligence-capable iPhone target only for now.
- Supported MVP devices: iPhone 15 Pro, iPhone 15 Pro Max, and all iPhone 16 / iPhone 17 models.
- Required OS: whichever iOS version provides Apple SpeechAnalyzer/SpeechTranscriber and Apple Foundation Models APIs.
- No backwards compatibility path yet for older devices or older iOS versions.
- Current source lives under `ThreeThings/`.

### Current MVP Scope

The current shippable milestone is a **voice-first local-AI TestFlight MVP** (capture → transcribe → extract → review → lock). The following are **explicitly not in the first TestFlight**: push notifications for start-of-day prompts, periodic nudges, and end-of-day notification actions; in-app **settings** for reminder intervals, quiet hours, intensity, or EOD times. Those ship after the on-device voice loop is stable.

- Record a short voice capture.
- Transcribe speech locally with Apple SpeechAnalyzer/SpeechTranscriber.
- Extract 1-3 candidate tasks locally with Apple Foundation Models.
- Review extracted tasks, extras, and overflow before locking.
- Type 1-3 tasks manually.
- Validate empty, duplicate, and overlong tasks.
- Show a pending review/finalization step before locking.
- Require explicit lock confirmation.
- Show a read-only locked execution view.
- Allow reversible completion toggles.
- Roll the focus day over at the local focus-day boundary.
- Track rolling 7-day momentum.
- Handle pending yesterday finalization before starting today's plan.

### Core Product Rules

- A daily plan must contain at least 1 task and at most 3 tasks.
- Tasks are only created during the daily capture flow.
- Once locked, task text cannot be edited until the next focus day.
- Completion can be toggled on locked tasks.
- Prior day task text is not carried forward.
- Previous plans are not archived as task history.
- Only minimal momentum metadata persists across sessions.

### Current Code Structure

- `ThreeThings/Models/`
  - `DailyPlan`
  - `TaskItem`
  - `InputMode`
  - `VoiceExtractionDraft`

- `ThreeThings/ViewModels/`
  - `AppViewModel`, the main app state and flow controller.

- `ThreeThings/Views/`
  - `RootView`
  - `TextCaptureView`
  - `PendingFinalizationView`
  - `LockedPlanView`
  - `ExtractionReviewView`
  - `VoiceCaptureView`

- `ThreeThings/Services/Extraction/`
  - `VoiceDraftExtracting` provider protocol; `HeuristicVoiceDraftExtractor` for simulator/tests.
  - `FoundationModelsVoiceDraftExtractor` calls Apple FM on device with a `@Generable` `GeneratedVoiceDraft` schema and the v12 extraction prompt.
  - `VoiceDraftPostProcessor.buildDraft` applies deterministic repair after the model: exact + semantic (Jaccard ≥ 0.55) dedup, promote extras → selected when room, cap at 3, recompute overflow.
  - `Eval/` contains the on-device eval runner + scorer; off-device prompt iteration lives in `evals/` (Python, Groq proxy).

- `ThreeThings/Services/Speech/`
  - `SpeechCaptureManager` orchestrates `AVAudioRecorder` + `SpeechAnalyzer`/`SpeechTranscriber`.
  - `LiveSpeechCapture` streams partial transcripts during recording (`SFSpeechRecognizer` + `AVAudioEngine` on device; scripted mock in simulator).

- `ThreeThings/Utilities/`
  - `FocusDay`, which owns focus-day identity and rollover logic.

### Voice And Extraction Direction

Voice capture and local LLM extraction are implemented and the primary MVP path.

Current flow:

1. User records speech via `SpeechCaptureManager`; `LiveSpeechCapture` streams partial transcripts.
2. Partials feed `AppViewModel.updateVoiceTranscriptSnapshot`, which debounces and runs **live extraction** through `FoundationModelsVoiceDraftExtractor` while the user is still speaking; on stop, a final flush runs immediately.
3. The extractor sends the transcript through the v12 prompt to Apple Foundation Models with `@Generable` schema enforcement (`GeneratedVoiceDraft`).
4. `VoiceDraftPostProcessor.buildDraft` applies deterministic repair (dedup, extras→selected promotion, overflow recompute).
5. User reviews the resulting `VoiceExtractionDraft` (selected + extras + overflow flag) before locking. Editing the draft pauses live re-extraction; "Apply latest voice" resyncs.

Extraction behavior is specified in `extraction_behavior.md` and exercised by `ThreeThings/Fixtures/voice_extraction_cases.json` (25 cases × 5 variants spanning literal, overflow, correction, duplicate, no-task, inference-trap, vague, substep, future-day, negative-commitment, ramble categories). Both an on-device Swift eval runner (`ThreeThings/Services/Extraction/Eval/`) and an off-device Python eval harness (`evals/`, Groq llama-3.1-8b proxy) test the prompt against this fixture.

Important privacy/current-design notes:

- Audio should stay on device.
- Transcript text should stay on device for MVP extraction.
- Cloud extraction is not part of the default MVP path.
- Manual text entry remains available as the fallback path.
- English-only for the initial release.
- MVP compatibility is intentionally narrow: iPhone 15 Pro/Pro Max and all iPhone 16/17 devices only, with the required iOS version for Apple's local speech and Foundation Models APIs.

## What Still Needs To Be Done

### Immediate MVP Work

Done:

- Real SpeechAnalyzer/SpeechTranscriber + live partial capture via `LiveSpeechCapture` + `SpeechCaptureManager`.
- Apple Foundation Models extraction (`FoundationModelsVoiceDraftExtractor`) returning structured `selectedTasks` / `extraCandidates` / `detectedMoreThanThree`.
- Voice + text capture, validation, review, and lock flow.
- Off-device eval harness for prompt iteration (Python + Groq proxy) and on-device Swift eval runner.

Remaining:

- Ensure locked plans persist correctly across app launches.
- Complete focus-day rollover behavior.
- Finalize the exact focus-day boundary decision and update docs/code consistently.
- Implement pending-yesterday finalization before a new day can start.
- Implement rolling 7-day momentum storage and display.
- Add unit tests for focus-day calculation, persistence, validation, and momentum logic.
- Add UI tests for the basic flow: type tasks -> review -> lock -> complete.
- Continue extraction-quality iteration: push every behavior category in `extraction_behavior.md` to avg@5 ≥ 4.5 on the on-device eval; consider an Apple FM LoRA adapter once production transcripts are available.

### Product Polish Before TestFlight

- Tighten visual design, spacing, typography, and empty states.
- Add clear lock-confirmation copy that makes the commitment feel intentional.
- Add small completion feedback when all locked tasks are done.
- Improve error states around invalid tasks and rollover edge cases.
- Review accessibility basics: Dynamic Type, VoiceOver labels, tap targets, and contrast.

### Deferred Until After Local Voice MVP

- Start-of-day notifications.
- Periodic focus nudges.
- End-of-day notification actions.
- Settings for reminders, quiet hours, reminder intensity, and prompt times.
- Older iPhone / older iOS compatibility.
- Cloud extraction provider implementation.
- Provider/API strategy decision for optional cloud fallback, such as hosted proxy or BYOK.

### V2 / Later Ideas

- Distraction detection using Screen Time / Family Controls entitlements.
- Distracting apps picker.
- Widgets.
- Live Activities.
- Apple Watch app.
- Siri Shortcuts.
- Multi-language support.
- Full onboarding flow.
- Alternative local model fallback for non-Apple-Foundation-Models devices.
