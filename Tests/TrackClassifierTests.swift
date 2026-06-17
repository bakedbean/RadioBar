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
        check("captured song: Beeef", TrackClassifier.isLikelySong("Beeef - Observational Eros"))
        check("captured song: Face to Face", TrackClassifier.isLikelySong("Face to Face - 10-9-8"))
        check("false-positive guard: Miley Cyrus (contains 'wers')", TrackClassifier.isLikelySong("Miley Cyrus - Flowers"))
        check("The Beatles - Hey Jude", TrackClassifier.isLikelySong("The Beatles - Hey Jude"))

        // Taglines / non-songs → false
        check("captured tagline: WERS", !TrackClassifier.isLikelySong("WERS - Boston's Uncommon Radio"))
        check("empty", !TrackClassifier.isLikelySong(""))
        check("whitespace only", !TrackClassifier.isLikelySong("   "))
        check("no separator", !TrackClassifier.isLikelySong("Some Announcement"))
        check("empty artist side", !TrackClassifier.isLikelySong(" - Title Only"))
        check("empty title side", !TrackClassifier.isLikelySong("Artist Only - "))

        if failures == 0 {
            print("\nAll tests passed")
        } else {
            print("\n\(failures) test(s) failed")
            exit(1)
        }
    }
}
