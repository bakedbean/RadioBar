import AppKit

// Menubar-only app: uses a custom AppDelegate via the traditional
// NSApplication delegate pattern rather than SwiftUI's @main App.
// This gives us full control over the NSStatusItem lifecycle.

let app = NSApplication.shared
app.setActivationPolicy(.accessory)  // No Dock icon

let delegate = AppDelegate()
app.delegate = delegate

app.run()
