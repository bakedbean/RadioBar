import AppKit
import Foundation

// Render the radio antenna SF Symbol at all required icon sizes,
// save as PNGs, then build an .icns file with iconutil.

let symbolName = "antenna.radiowaves.left.and.right"
let outputDir = URL(fileURLWithPath: "/Users/eben/RadioBar/build/AppIcon.iconset")
try? FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

let sizes: [(name: String, size: CGFloat)] = [
    ("icon_16x16", 16),
    ("icon_16x16@2x", 32),
    ("icon_32x32", 32),
    ("icon_32x32@2x", 64),
    ("icon_128x128", 128),
    ("icon_128x128@2x", 256),
    ("icon_256x256", 256),
    ("icon_256x256@2x", 512),
    ("icon_512x512", 512),
    ("icon_512x512@2x", 1024),
]

guard let symbol = NSImage(systemSymbolName: symbolName, accessibilityDescription: "RadioBar") else {
    print("ERROR: SF Symbol not found")
    exit(1)
}

// Configure as template with a tint color so it's visible
let tintColor = NSColor.controlAccentColor

for (name, size) in sizes {
    let rect = NSRect(x: 0, y: 0, width: size, height: size)
    let image = NSImage(size: NSSize(width: size, height: size))

    image.lockFocus()
    tintColor.setFill()
    rect.fill()

    // Center and scale the symbol
    let padding = size * 0.15
    let symbolRect = rect.insetBy(dx: padding, dy: padding)
    symbol.draw(in: symbolRect, from: .zero, operation: .destinationAtop, fraction: 1.0)
    image.unlockFocus()

    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        print("ERROR: Failed to render \(name)")
        continue
    }

    let fileURL = outputDir.appendingPathComponent("\(name).png")
    try png.write(to: fileURL)
    print("  \(name).png (\(Int(size))x\(Int(size)))")
}

print("\nSaved to \(outputDir.path)")
print("Run: iconutil -c icns \(outputDir.path) -o /Users/eben/RadioBar/build/AppIcon.icns")
