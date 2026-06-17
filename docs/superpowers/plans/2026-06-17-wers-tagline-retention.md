# WERS Tagline Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the last real track displayed when WERS pushes a generic station tagline into the stream metadata, falling back to the station name only after a long non-music gap.

**Architecture:** Add a pure `TrackClassifier` that decides whether a `StreamTitle` is a real song (`Artist - Title`) or a station tagline. In `AppDelegate`'s metadata handler, only commit *songs* to the display; ignore taglines so the last real track is retained. A one-shot staleness `Timer`, reset on each real song, falls back to the station name after ~7 minutes of no songs.

**Tech Stack:** Swift + AppKit, compiled with `swiftc` via the existing `Makefile` (no SwiftPM, no XCTest). Testable units are Foundation-only and tested with a standalone `swiftc`-compiled assertion runner.

## Global Constraints

- Build system is `swiftc` driven by `Makefile`; there is **no SwiftPM and no XCTest**. New testable units MUST be Foundation-only so they compile and run standalone.
- Every new `.swift` file that ships in the app MUST be added to the `SOURCES` variable in `Makefile`.
- Files with top-level executable code compiled alongside other files MUST use `@main` (swiftc only allows bare top-level code in a file literally named `main.swift`).
- WERS stream URL: `https://playerservices.streamtheworld.com/api/livestream-redirect/WERSFMAAC.aac`
- The staleness fallback timeout is the one tuning knob; default `7 * 60` seconds, adjusted from observed cadence in Task 1.

---

## File Structure

- **Create** `tools/capture_metadata.swift` — throwaway diagnostic that reuses `MetadataParser` to print live `StreamTitle` values with timestamps. Used to observe real song vs. tagline strings and update cadence.
- **Create** `Sources/TrackClassifier.swift` — pure `enum TrackClassifier` with `isLikelySong(_:) -> Bool` and a tagline-marker list. Foundation-only, no AppKit.
- **Create** `Tests/TrackClassifierTests.swift` — standalone `@main` assertion runner for `TrackClassifier`.
- **Modify** `Makefile` — add `TrackClassifier.swift` to `SOURCES`; add `test` and `capture` targets; extend `.PHONY`.
- **Modify** `Sources/AppDelegate.swift` — classify-and-retain in `onTrackUpdate`; add staleness timer property + helpers; invalidate the timer on station switch in `resetArtwork()`.

---

## Task 1: Live metadata capture tool

Produces the real-world data that fixes the classifier's tagline list and confirms the staleness timeout. No app behavior changes.

**Files:**
- Create: `tools/capture_metadata.swift`
- Modify: `Makefile` (add `capture` target, extend `.PHONY`)

**Interfaces:**
- Consumes: `MetadataParser` (existing, `Sources/MetadataParser.swift`) — `init()`, `var onTrackUpdate: ((String?) -> Void)?`, `var onStationName: ((String?) -> Void)?`, `var onError: ((String) -> Void)?`, `func connect(to: URL)`.
- Produces: a console log of `<ISO8601 timestamp>\t<StreamTitle>` lines, and recorded findings (tagline strings + max gap between real songs) appended to this plan's Task 2/Task 3 notes.

- [ ] **Step 1: Write the capture tool**

Create `tools/capture_metadata.swift`:

```swift
import Foundation

// Reuses the app's real MetadataParser (Foundation-only) to dump live ICY
// StreamTitle values with timestamps, so we can see exactly what WERS sends
// for songs vs. taglines and how often real songs arrive.
@main
struct CaptureMetadata {
    static func main() {
        let defaultURL = "https://playerservices.streamtheworld.com/api/livestream-redirect/WERSFMAAC.aac"
        let urlString = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : defaultURL

        guard let url = URL(string: urlString) else {
            FileHandle.standardError.write(Data("Invalid URL: \(urlString)\n".utf8))
            exit(1)
        }

        let parser = MetadataParser()
        let formatter = ISO8601DateFormatter()

        parser.onTrackUpdate = { title in
            print("\(formatter.string(from: Date()))\t\(title ?? "<nil>")")
            fflush(stdout)
        }
        parser.onStationName = { name in
            print("# station: \(name ?? "<nil>")")
            fflush(stdout)
        }
        parser.onError = { msg in
            FileHandle.standardError.write(Data("# error: \(msg)\n".utf8))
        }

        print("# capturing \(url.absoluteString) — Ctrl-C to stop")
        fflush(stdout)
        parser.connect(to: url)
        RunLoop.main.run()
    }
}
```

- [ ] **Step 2: Add the `capture` target to the Makefile**

In `Makefile`, change the `.PHONY` line and add a `capture` target. Replace:

```make
.PHONY: build run clean icon
```

with:

```make
.PHONY: build run clean icon test capture
```

and add this target after the `run` target:

```make
capture:
	@mkdir -p $(BUILD_DIR)
	swiftc -o $(BUILD_DIR)/capture-metadata Sources/MetadataParser.swift tools/capture_metadata.swift
	./$(BUILD_DIR)/capture-metadata
```

- [ ] **Step 3: Build the capture tool**

Run: `make capture`
Expected: compiles cleanly and prints `# capturing https://playerservices...` then begins emitting timestamped `StreamTitle` lines within ~30s. (It runs until Ctrl-C.)

- [ ] **Step 4: Capture a full song→tagline cycle while the station is playing music**

Let it run **at least 20–30 minutes** so it spans several songs and at least one switch to the WERS tagline. Capture to a file for review:

Run: `make capture | tee /tmp/wers-capture.log` (Ctrl-C to stop after the window)
Expected: multiple lines. Songs look like `Artist - Title`; taglines look like a station promo string with no `Artist - Title` structure.

- [ ] **Step 5: Record findings**

From `/tmp/wers-capture.log`, note:
1. The exact tagline string(s) WERS emits (verbatim) — these seed `TrackClassifier.taglineMarkers` in Task 2.
2. The **maximum gap in minutes between two real-song lines** during continuous music — this confirms whether the 7-minute staleness timeout in Task 3 is safely longer than a normal inter-song gap.

Write these two findings into the commit message for this task. No code beyond the tool changes.

- [ ] **Step 6: Commit**

```bash
git add tools/capture_metadata.swift Makefile
git commit -m "feat: add WERS metadata capture tool

Observed taglines: <verbatim strings>
Max inter-song gap: <N> min"
```

---

## Task 2: TrackClassifier (song vs. tagline)

**Files:**
- Create: `Sources/TrackClassifier.swift`
- Create: `Tests/TrackClassifierTests.swift`
- Modify: `Makefile` (add `test` target; add `TrackClassifier.swift` to `SOURCES`)

**Interfaces:**
- Consumes: nothing (Foundation only).
- Produces: `enum TrackClassifier { static func isLikelySong(_ streamTitle: String) -> Bool; static var taglineMarkers: [String] }`. Consumed by `AppDelegate` in Task 3.

- [ ] **Step 1: Write the failing test**

Create `Tests/TrackClassifierTests.swift`:

```swift
import Foundation

@main
struct TrackClassifierTests {
    static func main() {
        var failures = 0
        func check(_ name: String, _ condition: Bool) {
            print(condition ? "✓ \(name)" : "✗ \(name)")
            if !condition { failures += 1 }
        }

        // Real songs → true
        check("artist-title", TrackClassifier.isLikelySong("The Beatles - Hey Jude"))
        check("artist-title with extra spaces", TrackClassifier.isLikelySong("  Phoebe Bridgers - Motion Sickness  "))
        check("hyphen in title text", TrackClassifier.isLikelySong("Sufjan Stevens - Should Have Known Better"))

        // Taglines / non-songs → false
        check("station tagline", !TrackClassifier.isLikelySong("WERS 88.9 FM"))
        check("promo line", !TrackClassifier.isLikelySong("Wicked Good Radio"))
        check("empty", !TrackClassifier.isLikelySong(""))
        check("whitespace only", !TrackClassifier.isLikelySong("   "))
        check("no separator", !TrackClassifier.isLikelySong("Some Announcement"))
        check("empty artist side", !TrackClassifier.isLikelySong(" - Title Only"))
        check("empty title side", !TrackClassifier.isLikelySong("Artist Only - "))
        check("tagline that contains a hyphen", !TrackClassifier.isLikelySong("WERS 88.9 - Boston"))

        if failures == 0 {
            print("\nAll tests passed")
        } else {
            print("\n\(failures) test(s) failed")
            exit(1)
        }
    }
}
```

- [ ] **Step 2: Add the `test` target and run it to verify it fails**

In `Makefile`, add this target after the `capture` target:

```make
test:
	@mkdir -p $(BUILD_DIR)
	swiftc -o $(BUILD_DIR)/trackclassifier-tests Sources/TrackClassifier.swift Tests/TrackClassifierTests.swift
	./$(BUILD_DIR)/trackclassifier-tests
```

Run: `make test`
Expected: FAIL — compile error `cannot find 'TrackClassifier' in scope` (the type does not exist yet). In compiled-language TDD, a compile failure is the red state.

- [ ] **Step 3: Write the minimal implementation**

Create `Sources/TrackClassifier.swift`:

```swift
import Foundation

/// Decides whether an ICY `StreamTitle` is a real song or a station tagline.
///
/// WERS (and other StreamTheWorld stations) emit `Artist - Title` for songs and
/// a promotional station string between songs. We keep the last real song on
/// screen by ignoring anything that classifies as a tagline.
enum TrackClassifier {

    /// Substrings (matched case-insensitively) that mark a StreamTitle as a
    /// station tagline rather than a song. Seed values below; replace/extend
    /// with the verbatim strings observed by the Task 1 capture tool.
    static var taglineMarkers: [String] = [
        "wers",
        "wicked good radio",
        "88.9",
    ]

    /// True if `streamTitle` looks like an actual song (`Artist - Title`) and
    /// not a station tagline.
    static func isLikelySong(_ streamTitle: String) -> Bool {
        let trimmed = streamTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }

        // Tagline backstop: reject known promo markers even if they contain " - ".
        let lower = trimmed.lowercased()
        for marker in taglineMarkers where lower.contains(marker) {
            return false
        }

        // Require "Artist - Title": a " - " separator with non-empty sides.
        guard let sep = trimmed.range(of: " - ") else { return false }
        let artist = trimmed[..<sep.lowerBound].trimmingCharacters(in: .whitespaces)
        let title = trimmed[sep.upperBound...].trimmingCharacters(in: .whitespaces)
        return !artist.isEmpty && !title.isEmpty
    }
}
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `make test`
Expected: every line prints `✓` and the final line is `All tests passed` (exit 0).

- [ ] **Step 5: Reconcile against captured data**

Cross-check `TrackClassifier` against the real strings from Task 1's `/tmp/wers-capture.log`:
- Every captured **tagline** must classify as `false`. If a real tagline slips through (returns `true`), add its distinctive verbatim substring to `taglineMarkers`, add a matching `check("...", !TrackClassifier.isLikelySong("<captured tagline>"))` line to the test, and re-run `make test`.
- Every captured **song** must classify as `true`. If a real song is wrongly rejected, add a `check("...", TrackClassifier.isLikelySong("<captured song>"))` line and adjust the rule (e.g. a too-broad marker) until `make test` passes.

- [ ] **Step 6: Add TrackClassifier to the app build**

In `Makefile`, add `Sources/TrackClassifier.swift` to the `SOURCES` variable so the app bundle includes it. Change:

```make
SOURCES = Sources/main.swift Sources/Station.swift Sources/MetadataParser.swift Sources/RadioPlayer.swift Sources/AppDelegate.swift Sources/ArtworkFetcher.swift Sources/GlobalHotkey.swift
```

to:

```make
SOURCES = Sources/main.swift Sources/Station.swift Sources/MetadataParser.swift Sources/RadioPlayer.swift Sources/AppDelegate.swift Sources/ArtworkFetcher.swift Sources/GlobalHotkey.swift Sources/TrackClassifier.swift
```

- [ ] **Step 7: Verify the app still builds**

Run: `make build`
Expected: `→ Built binary` with no errors.

- [ ] **Step 8: Commit**

```bash
git add Sources/TrackClassifier.swift Tests/TrackClassifierTests.swift Makefile
git commit -m "feat: add TrackClassifier to distinguish songs from station taglines"
```

---

## Task 3: Retain last song + staleness fallback in AppDelegate

**Files:**
- Modify: `Sources/AppDelegate.swift` — `onTrackUpdate` handler (currently `Sources/AppDelegate.swift:319-329`); add timer property near `currentTrack` (`:34-36`); add timer helpers; invalidate timer in `resetArtwork()` (`:393-404`).

**Interfaces:**
- Consumes: `TrackClassifier.isLikelySong(_:)` from Task 2; existing `currentTrack`, `currentTrackYear`, `refreshNowPlayingUI(track:)`, `fetchArtwork(for:)`, `resetArtwork()`.
- Produces: no new public surface — behavior change only.

- [ ] **Step 1: Add the staleness timer property**

In `Sources/AppDelegate.swift`, find (`:34-36`):

```swift
    // Current track + its release year (from iTunes lookup), for the popup label.
    private var currentTrack: String?
    private var currentTrackYear: Int?
```

Add immediately below it:

```swift

    // One-shot timer that clears the displayed track after a long music gap, so
    // an ended song doesn't linger forever during news/long talk segments. Reset
    // on every real song; fires only when no song has arrived for the timeout.
    private var staleTrackTimer: Timer?
    private let staleTrackTimeout: TimeInterval = 7 * 60  // adjust per Task 1 cadence
```

- [ ] **Step 2: Replace the metadata handler with classify-and-retain**

In `Sources/AppDelegate.swift`, find the handler (`:318-329`):

```swift
        // Metadata → update menubar title + now-playing label + artwork
        metadataParser.onTrackUpdate = { [weak self] track in
            DispatchQueue.main.async {
                // New track — clear the previous year until the lookup fills it in.
                self?.currentTrack = (track?.isEmpty == false) ? track : nil
                self?.currentTrackYear = nil
                self?.refreshNowPlayingUI(track: track)
                if let track, !track.isEmpty {
                    self?.fetchArtwork(for: track)
                }
            }
        }
```

Replace it with:

```swift
        // Metadata → update display only for *real songs*. WERS pushes a generic
        // station tagline between songs; ignoring it keeps the last real track on
        // screen. The staleness timer handles eventual fallback to the station.
        metadataParser.onTrackUpdate = { [weak self] track in
            DispatchQueue.main.async {
                guard let self else { return }
                guard let track, TrackClassifier.isLikelySong(track) else {
                    return  // tagline or junk — retain the current track
                }
                // New song — clear the previous year until the lookup fills it in.
                self.currentTrack = track
                self.currentTrackYear = nil
                self.refreshNowPlayingUI(track: track)
                self.fetchArtwork(for: track)
                self.startStaleTrackTimer()
            }
        }
```

- [ ] **Step 3: Add the timer helper methods**

In `Sources/AppDelegate.swift`, add these two methods inside the `// MARK: - Callbacks` area (immediately after the closing brace of `setupCallbacks()`, around `:360`):

```swift

    /// (Re)start the one-shot staleness timer. Called on every real song.
    private func startStaleTrackTimer() {
        staleTrackTimer?.invalidate()
        staleTrackTimer = Timer.scheduledTimer(withTimeInterval: staleTrackTimeout,
                                                repeats: false) { [weak self] _ in
            self?.clearStaleTrack()
        }
    }

    /// Fired when no real song has arrived for `staleTrackTimeout`. Drops the
    /// stale track so the UI falls back to the station name.
    private func clearStaleTrack() {
        currentTrack = nil
        currentTrackYear = nil
        refreshNowPlayingUI(track: nil)
    }
```

- [ ] **Step 4: Invalidate the timer on station switch**

In `Sources/AppDelegate.swift`, find `resetArtwork()` (`:393-404`). It already clears `currentTrack`/`currentTrackYear`. Add timer cleanup. Change:

```swift
    private func resetArtwork() {
        artworkContainer?.frame.size.height = 1
        artworkImageView?.image = nil
        currentTrack = nil
        currentTrackYear = nil
```

to:

```swift
    private func resetArtwork() {
        artworkContainer?.frame.size.height = 1
        artworkImageView?.image = nil
        currentTrack = nil
        currentTrackYear = nil
        staleTrackTimer?.invalidate()
        staleTrackTimer = nil
```

- [ ] **Step 5: Build**

Run: `make build`
Expected: `→ Built binary` with no errors.

- [ ] **Step 6: Manual smoke verification against live WERS**

This wiring is AppKit/runloop-bound, so verify by running the app (the classifier itself is covered by `make test`):

Run: `make run`
Then, with WERS selected and playing:
1. Confirm the menubar + "Now Playing" show a real `Artist - Title` while music plays.
2. Wait through the end of a track into the tagline window. Expected: the menubar/popup **keep showing the last real song** instead of switching to the WERS tagline.
3. (Optional, slow) Confirm that during a genuinely long non-music stretch the display eventually falls back to the station name after ~7 minutes.

If step 2 still shows a tagline, the tagline string was not caught — add its verbatim marker to `TrackClassifier.taglineMarkers` (Task 2) and a regression test, then rebuild.

- [ ] **Step 7: Commit**

```bash
git add Sources/AppDelegate.swift
git commit -m "feat: retain last song over WERS tagline with staleness fallback"
```

---

## Self-Review Notes

- **Spec coverage:** classifier (Task 2) ✓; retention via not-overwriting `currentTrack` (Task 3 Step 2) ✓; staleness timer + station-name fallback (Task 3 Steps 1,3) ✓; both surfaces retained — automatic since menubar and popup both read `currentTrack` ✓; station-switch reset (Task 3 Step 4) ✓; first-connect-during-tagline — handled because a tagline is ignored and `currentTrack` stays nil → station-name fallback ✓; capture-real-data first step (Task 1) ✓; classifier unit tests (Task 2) ✓.
- **Timer reset semantics:** the timer is reset only on a *real song*, so it never fires during normal music (songs arrive well within the timeout) and only triggers after a sustained no-song gap — exactly the "last song, then fall back" behavior the user chose.
- **Types consistent:** `TrackClassifier.isLikelySong(_:)` / `taglineMarkers` referenced identically in Tasks 2 and 3.
