# Local voice stack — SDK & availability

This project targets **iOS 26+** so it can use:

| Capability | Apple API surface | Runtime checks |
|------------|-------------------|----------------|
| On-device speech-to-text | `Speech` — `SpeechAnalyzer`, `SpeechTranscriber`, preset **`.transcription`**, `analyzeSequence(from: AVAudioFile)` | `DefaultSpeechTranscriber` wraps `AppleOnDeviceSpeechTranscriber` (reads the recorded file via `AVAudioFile(forReading:)`). |
| On-device extraction | `FoundationModels` — `SystemLanguageModel`, `LanguageModelSession`, `@Generable` guided output | `FoundationModelsVoiceDraftExtractor` checks `SystemLanguageModel.default.isAvailable` and `supportsLocale(_:)` before prompting; otherwise throws `VoiceDraftExtractionError.modelUnavailable` / `localeUnsupported` (user gets **Type instead**). |
| Microphone + legacy speech auth | `AVAudioApplication.requestRecordPermission()`, `SFSpeechRecognizer.requestAuthorization` | `SystemRecordingPermissionGate`; failures map to `SpeechCaptureManager.Phase.failed` with a clear message. |

## Simulator vs device

- **Simulator (`targetEnvironment(simulator)`)**: `LiveSpeechCaptureFactory.default()` returns **`MockLiveSpeechCapture`** (scripted partials + final string). `AppVoiceDraftExtractorFactory.default()` returns `HeuristicVoiceDraftExtractor` (deterministic, no Apple Intelligence required). `SpeechCaptureManager` still exercises permission + (when allowed) `AVAudioRecorder` + `SpeechAnalyzer` if the simulator supports it; transcription may fail — UI should surface **Type instead**.
- **Device**: `LiveSpeechCaptureFactory` uses **`SFSpeechLiveCapture`** (`SFSpeechRecognizer` + `AVAudioEngine` tap). `stop()` ends audio and waits for a final recognition callback (or timeout) before cleanup so the last transcript is not dropped. Factory extraction uses `FoundationModelsVoiceDraftExtractor` for real guided generation.

## DEBUG speech diagnostics (device)

- On **DEBUG** device builds, the voice screen shows a short **`speechDiagnosticLine`** fed by `SFSpeechLiveCapture` (`os.Logger` + `Notification.Name.threeThingsSpeechPipelineDebug`): recognizer readiness, buffer-append counts (throttled), partial/final counts, errors, and stop timing.
- **Console**: filter subsystem `com.ismaelrobles.threethings` category `SpeechLive`.

## Real-device verification (voice → transcript → extraction)

1. Build **DEBUG** to a physical iPhone (iOS 26+), grant **Microphone** + **Speech Recognition**.
2. Open voice capture, tap **Start speaking**; say a short three-task phrase (e.g. “Tomorrow buy milk, call mom, and book a haircut”).
3. Confirm **partial text updates** while still recording.
4. Tap **Stop**; confirm the **final transcript** remains (not blank) and matches what you said closely enough to proceed.
5. Confirm the app moves into **live extraction / review** (`LiveExtractionScheduler`: debounced partials via `updateVoiceTranscriptSnapshot`, final flush via `ingestFinalTranscript` on stop) without needing **Type instead** unless the model is unavailable for your locale.
6. **Level meter**: while recording, the fixed bar meter should stay **mostly flat in silence** and **pulse up when you speak** (bars do not scroll sideways—only height reflects level); after **Stop** or **Cancel**, it should **reset** (no stale high bars during “Finishing transcript…”).

## Tests

- Unit tests inject `HeuristicVoiceDraftExtractor()` into `AppViewModel` for stable extraction.
- `SpeechCaptureManagerTests` covers permission denial, cancel/reset, scripted partial→final flow, **empty `stop()` merged with last partial** (`returnEmptyStringFromStop`), **`stop()` throws → failed phase**, **no speech detected** when both partials and final are empty, and **`currentAudioLevel`** (mock-driven meter updates while recording, reset on cancel / after stop).

## `xcodebuild` example

```bash
xcodebuild test -scheme "ThreeThings" -project "ThreeThings.xcodeproj" \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro,OS=26.3.1'
```
