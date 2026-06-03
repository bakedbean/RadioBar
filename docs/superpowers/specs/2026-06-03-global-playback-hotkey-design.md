# Global Play/Pause Hotkey — Design

**Date:** 2026-06-03
**Status:** Approved (pending implementation plan)

## Problem

RadioBar can toggle play/pause with the spacebar, but only while the app is
focused. The Play/Pause menu item uses a menu **key equivalent**
(`keyEquivalent: " "`, `Sources/AppDelegate.swift:134`), and macOS delivers key
equivalents only to the active app's key window. The user wants to start/stop the
stream from anywhere, regardless of which app is in focus.

## Decision

Add a **system-wide hotkey** bound to **`⌃⌥⌘ + Space`** (Control–Option–Command +
Space), implemented with the Carbon `RegisterEventHotKey` API.

### Why this mechanism

Three mechanisms can trigger an action globally on macOS:

| Mechanism | Permission | Notes |
|-----------|-----------|-------|
| Media play/pause key (`MPRemoteCommandCenter`) | none | Contended with Music.app / Spotify |
| **Carbon `RegisterEventHotKey`** | **none** | **Dedicated combo, never contended — chosen** |
| `NSEvent` global monitor / `CGEventTap` | Accessibility | Can observe but not consume keys; heavier |

`RegisterEventHotKey` was chosen because it needs **no Accessibility permission**,
the combo is exclusively owned by RadioBar, and it can consume the keystroke so it
never leaks to the focused app.

### Why this key

- **`⌃⌥⌘`** is the de-facto convention for custom global app shortcuts. System
  shortcuts and most apps use one or two modifiers, so reserving all three avoids
  collisions (Spotlight is `⌘Space`, previous input source is `⌃Space`, the
  emoji/character viewer is `⌃⌘Space` — adding `⌥` clears all of them).
- **`Space`** preserves the existing in-app spacebar muscle memory; the chord is
  simply "the global version of the same key."

A Carbon hotkey is a **chord** (keys held together), not a true leader *sequence*
(prefix, release, then key — which would require a `CGEventTap` + Accessibility).
For a single action the chord is simpler and permission-free.

## Architecture

One new, self-contained component — `GlobalHotkey` — wraps `RegisterEventHotKey`
behind a Swift callback. `AppDelegate` owns one instance and points its callback at
the existing `togglePlayPause()`. The global hotkey becomes a **second entry point**
into the play/pause logic that already exists; nothing else changes.

```
⌃⌥⌘+Space (anywhere)
      │
      ▼
Carbon event target ──► C event handler ──► GlobalHotkey's Swift closure
                                                      │
                                                      ▼ (on main thread)
                                            AppDelegate.togglePlayPause()  ← existing logic
                                                      │
                                                      ▼
                                  player.togglePlayPause() + Combine state callback
                                  refreshes menubar title & Play/Pause label
```

## Components

### New: `Sources/GlobalHotkey.swift`

A small class:

- `init(keyCode: UInt32, modifiers: UInt32, handler: @escaping () -> Void)` —
  registers the hotkey and installs one application-level event handler for
  `kEventHotKeyPressed` (event class `kEventClassKeyboard`).
- Bridges the C callback to Swift by passing `self` through the handler's
  `userData` pointer (`Unmanaged.passUnretained(self).toOpaque()`), recovering it
  inside the handler, and invoking the stored `handler` on the main thread.
- `deinit` calls `UnregisterEventHotKey` and `RemoveEventHandler` for clean
  teardown — no dangling system registration.

For this binding:
- `keyCode = 49` (`kVK_Space`)
- `modifiers = UInt32(controlKey | optionKey | cmdKey)` (Carbon modifier constants)

### Changed: `Sources/AppDelegate.swift`

- Add stored property `private var globalHotkey: GlobalHotkey?`.
- In `applicationDidFinishLaunching`, construct it with
  `{ [weak self] in self?.togglePlayPause() }`.

Holding the instance in a property is **required**: the Carbon registration lives
in the OS, but the Swift object holding the self-pointer and handler must outlive
the launch function. If it deallocates, `deinit` unregisters the hotkey and the
chord goes dead.

### Changed: `Makefile`

- Append `Sources/GlobalHotkey.swift` to the `SOURCES` list.
- Add `-framework Carbon` to the `swiftc` line (Carbon is not linked today).

## Data Flow

1. User presses `⌃⌥⌘+Space` in any app.
2. Carbon delivers a `kEventHotKeyPressed` event to RadioBar's application event
   target (delivered even when RadioBar is not focused).
3. The installed C handler fires, recovers the `GlobalHotkey` instance from
   `userData`, and dispatches the stored closure to the main thread.
4. The closure calls `AppDelegate.togglePlayPause()` — the same method the menu
   item uses.
5. Existing logic toggles the player; the `RadioPlayer.onPlaybackStateChange`
   Combine callback refreshes the menubar title and Play/Pause label automatically,
   regardless of what triggered the toggle.

Routing through `togglePlayPause()` (not the player directly) keeps the UI correct
for free and reuses the "nothing loaded → pick first station" behavior.

## Error Handling

`RegisterEventHotKey` returns an `OSStatus`. If it is not `noErr` (rare — e.g.
another app already grabbed the exact combo), `GlobalHotkey` logs a message and the
app continues fully functional via the menu, just without the global shortcut. No
crash, no silent failure.

## Testing

This is OS-level global behavior, verified manually rather than unit-tested:

1. `make run`.
2. Select a station and start playback.
3. Switch focus to a different app (e.g. Safari).
4. Press `⌃⌥⌘+Space` — confirm playback toggles and the menubar updates.
5. Press again — confirm it toggles back.

The first launch also confirms `RegisterEventHotKey` returns `noErr`.

## Out of Scope (YAGNI)

- User-configurable / rebindable hotkey (single fixed binding for now).
- Media-key (`MPRemoteCommandCenter`) integration.
- Additional global shortcuts (next/previous station, volume).
