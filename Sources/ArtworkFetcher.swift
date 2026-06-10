import AppKit

/// Fetches album artwork from the iTunes Search API using artist + song title.
/// Caches results in-memory to avoid redundant network calls.
final class ArtworkFetcher {

    /// What a lookup yields: cover art plus the track's release year, both
    /// pulled from the same iTunes search result. Either may be nil.
    struct TrackInfo {
        let image: NSImage?
        let year: Int?
    }

    private var cache: [String: TrackInfo] = [:]
    private var inFlight: Set<String> = []

    /// Fetch artwork + release year for a track. Returns cached result
    /// immediately if available. Otherwise queries iTunes API and calls the
    /// callback on completion.
    func fetch(artistSong: String, completion: @escaping (TrackInfo) -> Void) {
        // Return cached result
        if let cached = cache[artistSong] {
            completion(cached)
            return
        }

        // Dedupe in-flight requests
        guard !inFlight.contains(artistSong) else { return }
        inFlight.insert(artistSong)

        let encoded = artistSong.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? artistSong
        let urlString = "https://itunes.apple.com/search?term=\(encoded)&entity=song&limit=1"
        guard let url = URL(string: urlString) else {
            inFlight.remove(artistSong)
            completion(TrackInfo(image: nil, year: nil))
            return
        }

        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let data, error == nil,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let results = json["results"] as? [[String: Any]],
                  let first = results.first else {
                self?.inFlight.remove(artistSong)
                DispatchQueue.main.async { completion(TrackInfo(image: nil, year: nil)) }
                return
            }

            // releaseDate looks like "1994-03-01T08:00:00Z" — take the leading year.
            let year = Self.parseYear(first["releaseDate"])

            guard let artworkURLString = first["artworkUrl100"] as? String else {
                // No artwork, but we may still have a year to show.
                self?.inFlight.remove(artistSong)
                DispatchQueue.main.async { completion(TrackInfo(image: nil, year: year)) }
                return
            }

            // Request 600x600 instead of 100x100
            let hiResURLString = artworkURLString.replacingOccurrences(of: "100x100", with: "600x600")
            guard let artworkURL = URL(string: hiResURLString) else {
                self?.inFlight.remove(artistSong)
                DispatchQueue.main.async { completion(TrackInfo(image: nil, year: year)) }
                return
            }

            // Hold the in-flight marker until this nested download finishes — clearing
            // it in the outer task would let a duplicate request start mid-download.
            URLSession.shared.dataTask(with: artworkURL) { [weak self] imageData, _, _ in
                defer { self?.inFlight.remove(artistSong) }
                guard let imageData, let image = NSImage(data: imageData) else {
                    DispatchQueue.main.async { completion(TrackInfo(image: nil, year: year)) }
                    return
                }
                let info = TrackInfo(image: image, year: year)
                self?.cache[artistSong] = info
                DispatchQueue.main.async { completion(info) }
            }.resume()
        }.resume()
    }

    /// Extracts the 4-digit year from an ISO-8601 release date string.
    private static func parseYear(_ value: Any?) -> Int? {
        guard let s = value as? String, s.count >= 4 else { return nil }
        return Int(s.prefix(4))
    }
}
