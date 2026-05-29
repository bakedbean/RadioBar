import AppKit

/// Fetches album artwork from the iTunes Search API using artist + song title.
/// Caches results in-memory to avoid redundant network calls.
final class ArtworkFetcher {

    private var cache: [String: NSImage] = [:]
    private var inFlight: Set<String> = []

    /// Fetch artwork for a track. Returns cached result immediately if available.
    /// Otherwise queries iTunes API and calls the callback on completion.
    func fetch(artistSong: String, completion: @escaping (NSImage?) -> Void) {
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
            completion(nil)
            return
        }

        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            defer { self?.inFlight.remove(artistSong) }

            guard let data, error == nil,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let results = json["results"] as? [[String: Any]],
                  let first = results.first,
                  let artworkURLString = first["artworkUrl100"] as? String else {
                DispatchQueue.main.async { completion(nil) }
                return
            }

            // Request 600x600 instead of 100x100
            let hiResURLString = artworkURLString.replacingOccurrences(of: "100x100", with: "600x600")
            guard let artworkURL = URL(string: hiResURLString) else {
                DispatchQueue.main.async { completion(nil) }
                return
            }

            URLSession.shared.dataTask(with: artworkURL) { [weak self] imageData, _, _ in
                guard let imageData, let image = NSImage(data: imageData) else {
                    DispatchQueue.main.async { completion(nil) }
                    return
                }
                self?.cache[artistSong] = image
                DispatchQueue.main.async { completion(image) }
            }.resume()
        }.resume()
    }
}
