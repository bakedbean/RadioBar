# WERS Tagline Retention — Design

**Date:** 2026-06-17
**Status:** Approved (pending spec review)

## Problem

RadioBar displays whatever the stream puts in the ICY `StreamTitle='...'` field,
verbatim, with no concept of "song" vs. "station tagline."

For WERS specifically, the station's metadata cycles like this:

1. The next track's metadata appears shortly *before* the current song finishes.
2. The real track data sticks around until roughly halfway through the next track.
3. The display then switches to a generic WERS tagline (e.g. "WERS 88.9 FM…").

The result: glancing at the menubar near the end of a track shows the generic
tagline, and the actual track data is lost. This is driven entirely by WERS — we
cannot change what the stream sends — so the fix must live on our side.

## Root cause

The only filter in the pipeline is an *empty-string* guard in
`MetadataParser.processMetadata` (`Sources/MetadataParser.swift:179`):

```swift
guard let title = extractStreamTitle(from: cleaned), !title.isEmpty else {
    return  // empty chunk — don't overwrite the current display
}
```

A WERS tagline is a non-empty string, so it passes the guard, fires
`onTrackUpdate`, and overwrites `currentTrack` in `AppDelegate.swift:319`. The app
has no way to tell a song from a tagline.

## Goal

When a tagline arrives, keep displaying the last real track instead of
overwriting it. During a genuinely long non-music stretch (news, extended talk),
fall back to the station name after a few minutes rather than showing a stale
song indefinitely.

## Design

### Component: `TrackClassifier` (`Sources/TrackClassifier.swift`)

A new, standalone, pure function:

```swift
func isLikelySong(_ streamTitle: String) -> Bool
```

Keeping it standalone makes it trivially unit-testable and keeps
`MetadataParser` a dumb byte transport. Rules (finalized from captured live data
— see Implementation step 1):

- **Reject** if it matches a known WERS tagline (a small list/regex backstop).
- Otherwise **accept** if it has `Artist - Title` structure: a ` - ` separator
  with non-empty text on both sides.

Pure `String -> Bool`, no I/O, no app state.

### Pipeline change: `AppDelegate.onTrackUpdate` (`AppDelegate.swift:319`)

Classification is domain logic, so it belongs in `AppDelegate`, not the parser.
On each incoming `StreamTitle`:

- **Classifies as a song** → update `currentTrack`, run the iTunes lookup as
  today, and **reset the staleness timer**.
- **Classifies as a tagline** → do nothing. `currentTrack` keeps its last real
  value, so both the menubar (`setMenubarTitle`) and the popup
  (`refreshNowPlayingUI`) keep showing the real song. Retention is automatic
  across both surfaces because both already read from `currentTrack`.

### Staleness timer

A `Timer` reset every time a *real song* arrives:

- Real song arrives → set `currentTrack`, restart the timer (~N minutes).
- Tagline arrives → ignored; timer keeps counting from the last real song.
- Timer fires → clear `currentTrack`, call `refreshNowPlayingUI(nil)`, which
  falls back to the station name.

During normal music the timer resets each song and never fires; it only kicks in
during an extended non-music block. **N is the one tuning knob**, derived from the
observed real-update cadence (default ~7 minutes).

### Edge cases

- **Station switch** → clear `currentTrack` and the timer so a WERS song never
  bleeds onto another station.
- **First connect during a tagline** → `currentTrack` is nil, the tagline is
  ignored, so we show the station name (not the tagline) until the first real
  song.
- **Manual "Refresh Metadata"** → reconnects; if WERS sends a tagline first, we
  retain whatever `currentTrack` held (or the station-name fallback if it was
  cleared). Acceptable.

## Implementation steps

1. **Capture real WERS metadata.** Tap the live stream for a while and record
   exactly what songs vs. taglines look like, and how often real updates arrive.
   This turns the classifier rules and the timeout `N` into facts, not guesses.
2. Implement `TrackClassifier` with unit tests against the captured strings.
3. Wire classification + retention + staleness timer into `AppDelegate`.
4. Handle the edge cases above (station switch, first connect).

## Testing

- Unit-test `TrackClassifier` against a table of captured real strings
  (songs → true, taglines → false).
- Test retention/timer behavior by feeding metadata strings through the handler
  (real → real → tagline should keep the real track; timer expiry should fall
  back to the station name).

## Out of scope (YAGNI)

- No visual indicator distinguishing "currently playing" from "last played."
- No machine-learning / fuzzy detection — a structural heuristic plus a small
  blocklist is sufficient.
- No changes to artwork/iTunes lookup behavior beyond gating it on a real song.
