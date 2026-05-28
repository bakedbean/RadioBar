import Foundation

/// Connects to an internet radio stream and extracts ICY (Shoutcast/Icecast)
/// in-band metadata — artist/track info — without decoding the audio.
///
/// Runs a parallel URLSession data task that reads raw stream bytes,
/// skips audio according to the `icy-metaint` interval, and parses
/// `StreamTitle='...'` chunks out of the metadata blocks.
final class MetadataParser: NSObject, URLSessionDataDelegate, @unchecked Sendable {

    // MARK: - Published state

    var onTrackUpdate: ((String?) -> Void)?
    var onStationName: ((String?) -> Void)?
    var onError: ((String) -> Void)?

    // MARK: - Internal state

    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var metaint: Int = 0
    private var audioBytesRemaining: Int = 0
    private var metaLengthRemaining: Int = 0
    private var metaBuffer = Data()
    private var streamActive = false

    // MARK: - Public API

    func connect(to url: URL) {
        disconnect()

        var request = URLRequest(url: url)
        request.setValue("1", forHTTPHeaderField: "Icy-MetaData")
        request.timeoutInterval = 30

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForResource = 3600   // 1-hour stream timeout
        config.timeoutIntervalForRequest = 30
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        task = session?.dataTask(with: request)
        task?.resume()
    }

    func disconnect() {
        task?.cancel()
        task = nil
        session?.invalidateAndCancel()
        session = nil
        streamActive = false
        metaint = 0
        audioBytesRemaining = 0
        metaLengthRemaining = 0
        metaBuffer = Data()
    }

    // MARK: - URLSessionDataDelegate

    func urlSession(_ session: URLSession,
                    dataTask: URLSessionDataTask,
                    didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        if let httpResponse = response as? HTTPURLResponse {
            let headers = httpResponse.allHeaderFields as? [String: String] ?? [:]

            if let metaintStr = headers["icy-metaint"] ?? headers["Icy-Metaint"],
               let val = Int(metaintStr), val > 0 {
                metaint = val
                audioBytesRemaining = val
            }

            let name = headers["icy-name"] ?? headers["Icy-Name"]
            if let name {
                DispatchQueue.main.async { [weak self] in
                    self?.onStationName?(name)
                }
            }
        }
        streamActive = true
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession,
                    dataTask: URLSessionDataTask,
                    didReceive data: Data) {
        guard metaint > 0, streamActive else { return }

        var offset = 0
        let count = data.count

        while offset < count {
            if audioBytesRemaining > 0 {
                // Skip audio bytes
                let consume = min(audioBytesRemaining, count - offset)
                offset += consume
                audioBytesRemaining -= consume

            } else if metaLengthRemaining == 0 {
                // Read metadata length byte (1 byte = N * 16 bytes of metadata)
                let metaLenByte = data[offset]
                offset += 1
                metaLengthRemaining = Int(metaLenByte) * 16

                if metaLengthRemaining == 0 {
                    // No metadata this interval → next audio chunk
                    audioBytesRemaining = metaint
                } else {
                    metaBuffer = Data()
                }

            } else {
                // Accumulate metadata bytes
                let consume = min(metaLengthRemaining, count - offset)
                metaBuffer.append(data.subdata(in: offset ..< (offset + consume)))
                offset += consume
                metaLengthRemaining -= consume

                if metaLengthRemaining == 0 {
                    processMetadata(metaBuffer)
                    audioBytesRemaining = metaint
                }
            }
        }
    }

    func urlSession(_ session: URLSession,
                    task: URLSessionTask,
                    didCompleteWithError error: Error?) {
        streamActive = false
        if let error {
            let nsErr = error as NSError
            // -999 = cancelled (we did it), not a real error
            if nsErr.code != -999 {
                DispatchQueue.main.async { [weak self] in
                    self?.onError?(error.localizedDescription)
                }
            }
        }
    }

    // MARK: - Metadata parsing

    private func processMetadata(_ data: Data) {
        // ICY spec says ISO-8859-1, but many stations send UTF-8.
        // Try UTF-8 first; fall back to Latin-1.
        let metaString: String
        if let s = String(data: data, encoding: .utf8) {
            metaString = s
        } else if let s = String(data: data, encoding: .isoLatin1) {
            metaString = s
        } else {
            return
        }

        let cleaned = metaString
            .replacingOccurrences(of: "\0", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        let title = extractStreamTitle(from: cleaned)
        DispatchQueue.main.async { [weak self] in
            self?.onTrackUpdate?(title)
        }
    }

    /// Extracts the value of `StreamTitle='...'` from an ICY metadata string.
    ///
    /// Format: `StreamTitle='Artist - Song';StreamUrl='https://...';`
    /// Returns `nil` if the title is empty or missing.
    private func extractStreamTitle(from raw: String) -> String? {
        guard let startRange = raw.range(of: "StreamTitle='") else { return nil }
        let searchStart = startRange.upperBound
        let remainder = raw[searchStart...]

        // Find closing quote — the value may contain escaped quotes,
        // but in practice the closing pattern is "';" (quote-semicolon)
        guard let endRange = remainder.range(of: "';") else {
            // Might be at end of string with just a trailing quote
            if let endQuote = remainder.range(of: "'", options: .backwards) {
                let val = String(remainder[..<endQuote.lowerBound])
                return val.isEmpty ? nil : val
            }
            return nil
        }
        let val = String(remainder[..<endRange.lowerBound])
        return val.isEmpty ? nil : val
    }
}
