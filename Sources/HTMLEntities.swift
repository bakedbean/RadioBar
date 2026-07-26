/// Decodes HTML/XML character entities that some stations embed in ICY
/// metadata (e.g. "Don&apos;t Stop"). Without decoding, the raw entity
/// reaches the menu bar, TrackClassifier, and the iTunes artwork lookup.
///
/// Pure Swift (no Foundation) so it stays trivially testable. Handles
/// numeric entities (decimal and hex) plus the named entities seen in
/// practice in stream metadata; anything unrecognized is left verbatim.
/// Single-pass, matching Python's html.unescape ("&amp;apos;" → "&apos;").
enum HTMLEntities {

    private static let named: [Substring: Character] = [
        "amp": "&", "apos": "'", "quot": "\"", "lt": "<", "gt": ">",
        "nbsp": "\u{00A0}",
        "ndash": "\u{2013}", "mdash": "\u{2014}", "hellip": "\u{2026}",
        "lsquo": "\u{2018}", "rsquo": "\u{2019}",
        "ldquo": "\u{201C}", "rdquo": "\u{201D}",
        "eacute": "\u{00E9}", "egrave": "\u{00E8}", "agrave": "\u{00E0}",
        "ccedil": "\u{00E7}", "ntilde": "\u{00F1}",
        "auml": "\u{00E4}", "ouml": "\u{00F6}", "uuml": "\u{00FC}",
        "deg": "\u{00B0}",
    ]

    // Longest valid body is 8 chars ("#1114111"); the semicolon can sit
    // one past that. Bounding the lookahead keeps a stray "&" from
    // scanning to a distant ";".
    private static let maxEntityLength = 10

    static func decode(_ text: String) -> String {
        guard text.contains("&") else { return text }
        var out = ""
        out.reserveCapacity(text.count)
        var i = text.startIndex
        while i < text.endIndex {
            let c = text[i]
            if c == "&" {
                let bodyStart = text.index(after: i)
                let searchEnd = text.index(bodyStart, offsetBy: maxEntityLength,
                                           limitedBy: text.endIndex) ?? text.endIndex
                if let semi = text[bodyStart..<searchEnd].firstIndex(of: ";"),
                   let decoded = decodeEntity(text[bodyStart..<semi]) {
                    out.append(decoded)
                    i = text.index(after: semi)
                    continue
                }
            }
            out.append(c)
            i = text.index(after: i)
        }
        return out
    }

    private static func decodeEntity(_ body: Substring) -> Character? {
        if body.hasPrefix("#") {
            let digits = body.dropFirst()
            let value: UInt32?
            if digits.hasPrefix("x") || digits.hasPrefix("X") {
                value = UInt32(digits.dropFirst(), radix: 16)
            } else {
                value = UInt32(digits, radix: 10)
            }
            guard let value, let scalar = Unicode.Scalar(value) else { return nil }
            return Character(scalar)
        }
        return named[body]
    }
}
