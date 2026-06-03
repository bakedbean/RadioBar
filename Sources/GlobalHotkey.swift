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
