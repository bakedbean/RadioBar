import Foundation

/// Decides whether an ICY `StreamTitle` is a real song or a station tagline.
///
/// WERS (and other StreamTheWorld stations) emit `Artist - Title` for songs and
/// a promotional station string between songs. We keep the last real song on
/// screen by ignoring anything that classifies as a tagline.
enum TrackClassifier {

    /// Substrings (matched case-insensitively) that mark a StreamTitle as a
    /// station tagline rather than a song.
    ///
    /// Uses "uncommon radio" — a distinctive phrase from the captured WERS tagline
    /// "WERS - Boston's Uncommon Radio" — instead of bare "wers" which would
    /// false-positive on songs like "Miley Cyrus - Flowers" (contains "wers").
    static var taglineMarkers: [String] = [
        "uncommon radio",
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
