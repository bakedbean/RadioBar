# Global Play/Pause Hotkey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toggle RadioBar's playback with a system-wide `⌃⌥⌘ + Space` hotkey that works regardless of which app is focused.

**Architecture:** A self-contained `GlobalHotkey` class wraps the Carbon `RegisterEventHotKey` API behind a Swift callback. `AppDelegate` owns one instance and routes its callback into the existing `togglePlayPause()`, making the hotkey a second entry point into the playback logic already in place.

**Tech Stack:** Swift + AppKit, Carbon (`Carbon.framework`) for the global hotkey, plain `swiftc` build via `make`.

**Testing note:** This project has no unit-test harness, and a global hotkey cannot be unit-tested (it depends on OS-level event routing). Verification is therefore (a) the build compiling cleanly and (b) a manual behavior check from another app. Both are spelled out as explicit steps below.

---

### Task 1: Add the `GlobalHotkey` component and link Carbon

**Files:**
- Create: `Sources/GlobalHotkey.swift`
- Modify: `Makefile:6` (SOURCES list) and `Makefile:15` (swiftc line)

- [ ] **Step 1: Create `Sources/GlobalHotkey.swift`**

```swift
import AppKit
import Carbon

/// Registers a system-wide keyboard shortcut using the Carbon
/// `RegisterEventHotKey` API. The shortcut fires its handler regardless of which
/// application is focused, and requires no Accessibility permission.
///
/// The instance MUST be retained for as long as the hotkey should stay active:
/// `deinit` unregisters it, so a dropped reference silently kills the shortcut.
final class GlobalHotkey {

    private var hotKeyRef: EventHotKeyRef?
    private var eventHandlerRef: EventHandlerRef?
    private let handler: () -> Void

    /// - Parameters:
    ///   - keyCode: A virtual key code (e.g. `kVK_Space`).
    ///   - modifiers: Carbon modifier flags (e.g. `controlKey | optionKey | cmdKey`).
    ///   - handler: Called on the main thread when the hotkey is pressed.
    /// - Returns: `nil` if the OS refuses to install the handler or register the
    ///   hotkey (e.g. the combo is already claimed). Callers should treat `nil` as
    ///   "no global shortcut" and continue.
    init?(keyCode: UInt32, modifiers: UInt32, handler: @escaping () -> Void) {
        self.handler = handler

        // Install one application-level handler for hotkey-pressed events.
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                      eventKind: UInt32(kEventHotKeyPressed))
        let selfPtr = Unmanaged.passUnretained(self).toOpaque()

        let installStatus = InstallEventHandler(
            GetApplicationEventTarget(),
            { _, _, userData -> OSStatus in
                guard let userData else { return OSStatus(eventNotHandledErr) }
                let instance = Unmanaged<GlobalHotkey>.fromOpaque(userData).takeUnretainedValue()
                DispatchQueue.main.async { instance.handler() }
                return noErr
            },
            1,
            &eventType,
            selfPtr,
            &eventHandlerRef
        )
        guard installStatus == noErr else {
            NSLog("GlobalHotkey: failed to install event handler (status \(installStatus))")
            return nil
        }

        // Register the hotkey itself. The signature is an arbitrary 4-char code
        // ('RADI') that distinguishes RadioBar's hotkeys from other apps'.
        let hotKeyID = EventHotKeyID(signature: OSType(0x5241_4449), id: 1)
        let registerStatus = RegisterEventHotKey(
            keyCode,
            modifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )
        guard registerStatus == noErr else {
            NSLog("GlobalHotkey: failed to register hotkey (status \(registerStatus))")
            if let eventHandlerRef { RemoveEventHandler(eventHandlerRef) }
            return nil
        }
    }

    deinit {
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        if let eventHandlerRef { RemoveEventHandler(eventHandlerRef) }
    }
}
```

- [ ] **Step 2: Add the new source file and Carbon framework to the Makefile**

In `Makefile`, change the `SOURCES` line (line 6) to append the new file:

```makefile
SOURCES = Sources/main.swift Sources/Station.swift Sources/MetadataParser.swift Sources/RadioPlayer.swift Sources/AppDelegate.swift Sources/ArtworkFetcher.swift Sources/GlobalHotkey.swift
```

And change the `swiftc` line (line 15) to link Carbon:

```makefile
	swiftc -o $@ -framework AppKit -framework AVFoundation -framework Carbon $(SOURCES)
```

- [ ] **Step 3: Build to verify it compiles**

Run: `make build`
Expected: ends with `→ Built binary` and no compiler errors. (The icon step may also run; that's fine.)

- [ ] **Step 4: Commit**

```bash
git add Sources/GlobalHotkey.swift Makefile
git commit -m "Add GlobalHotkey component wrapping Carbon RegisterEventHotKey

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire the hotkey into AppDelegate

**Files:**
- Modify: `Sources/AppDelegate.swift` (import at line 1-2, new property near line 16, registration in `applicationDidFinishLaunching` near line 30-37)

- [ ] **Step 1: Import Carbon for the key/modifier constants**

At the top of `Sources/AppDelegate.swift`, add `import Carbon` alongside the existing imports:

```swift
import AppKit
import Carbon
import Combine
```

- [ ] **Step 2: Add a property to retain the hotkey**

In the `// MARK: - Status item` section, after the `statusItem` declaration (around line 16), add:

```swift
    // MARK: - Global hotkey

    /// Retained for the app's lifetime so the ⌃⌥⌘+Space registration stays alive.
    private var globalHotkey: GlobalHotkey?
```

- [ ] **Step 3: Register the hotkey at launch**

In `applicationDidFinishLaunching`, after the existing `setupCallbacks()` call and before `setMenubarTitle(defaultText:)`, add:

```swift
        // Global hotkey: ⌃⌥⌘+Space toggles play/pause from any app.
        globalHotkey = GlobalHotkey(
            keyCode: UInt32(kVK_Space),
            modifiers: UInt32(controlKey | optionKey | cmdKey),
            handler: { [weak self] in self?.togglePlayPause() }
        )
        if globalHotkey == nil {
            NSLog("RadioBar: global play/pause hotkey unavailable")
        }
```

The resulting method body should read:

```swift
    func applicationDidFinishLaunching(_ notification: Notification) {
        setupStatusItem()
        setupCallbacks()

        // Global hotkey: ⌃⌥⌘+Space toggles play/pause from any app.
        globalHotkey = GlobalHotkey(
            keyCode: UInt32(kVK_Space),
            modifiers: UInt32(controlKey | optionKey | cmdKey),
            handler: { [weak self] in self?.togglePlayPause() }
        )
        if globalHotkey == nil {
            NSLog("RadioBar: global play/pause hotkey unavailable")
        }

        setMenubarTitle(defaultText: "RadioBar")

        // Load last station and auto-play if the user wants
        // (opted out for v1 — manual play)
    }
```

- [ ] **Step 4: Build to verify it compiles**

Run: `make build`
Expected: ends with `→ Built binary` and no compiler errors.

- [ ] **Step 5: Manual behavior verification**

Run: `make run`

Then:
1. Click the RadioBar menubar icon and select a station; confirm audio starts.
2. Switch focus to a different app (e.g. click into Safari).
3. Press `⌃⌥⌘ + Space`. Expected: audio stops and the menubar title/Play-Pause label update — without RadioBar being focused.
4. Press `⌃⌥⌘ + Space` again. Expected: audio resumes.
5. With nothing ever played yet (fresh launch, no station selected), press the chord. Expected: the first station starts playing (this exercises the existing "nothing loaded → pick first station" branch in `togglePlayPause()`).

If any step fails, stop and debug before committing.

- [ ] **Step 6: Commit**

```bash
git add Sources/AppDelegate.swift
git commit -m "Bind global hotkey (ctrl-opt-cmd-space) to play/pause

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Mechanism (Carbon `RegisterEventHotKey`, no Accessibility) → Task 1 component. ✓
- Key binding `⌃⌥⌘ + Space` (`kVK_Space` + `controlKey|optionKey|cmdKey`) → Task 2 Step 3. ✓
- `GlobalHotkey` component with failable init, `userData` self-bridging, main-thread dispatch, `deinit` teardown → Task 1 Step 1. ✓
- `AppDelegate` retained property + construction routed to `togglePlayPause()` → Task 2 Steps 2-3. ✓
- Makefile: source list + `-framework Carbon` → Task 1 Step 2. ✓
- Error handling: non-`noErr` logs and continues (failable init → nil) → Task 1 Step 1 + Task 2 Step 3 nil-check. ✓
- Testing: build + manual cross-app check → Task 1 Step 3, Task 2 Steps 4-5. ✓
- Out of scope (rebindable key, media key, extra shortcuts) → not implemented, correctly. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/vague steps; every code step shows complete code. ✓

**Type consistency:** `GlobalHotkey(keyCode:modifiers:handler:)` defined in Task 1 matches the call site in Task 2. Property name `globalHotkey` consistent. `togglePlayPause()` matches existing `AppDelegate.swift:365`. ✓
