import Foundation

/// Connects to an internet radio stream and extracts ICY (Shoutcast/Icecast)
/// in-band metadata — artist/track info — without decoding the audio.
///
/// Runs a parallel URLSession data task that reads raw stream bytes,
/// skips audio according to the `icy-metaint` interval, and parses
/// `StreamTitle='...'` chunks out of the metadata blocks.
///
/// Auto-retries up to 3 times on connection failure with a 5-second backoff.
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

    // Auto-retry
    private var lastURL: URL?
    private var retryCount = 0
    private let maxRetries = 3

    // MARK: - Public API

    func connect(to url: URL) {
        disconnect()
        lastURL = url
        retryCount = 0
        startConnection(to: url)
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
        retryCount = 0
    }

    // MARK: - Private

    private func startConnection(to url: URL) {
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

    private func scheduleRetry() {
        guard let url = lastURL, retryCount < maxRetries else { return }
        retryCount += 1
        let delay = DispatchTime.now() + .seconds(5)
        DispatchQueue.global().asyncAfter(deadline: delay) { [weak self] in
            self?.startConnection(to: url)
        }
    }

    // MARK: - URLSessionDataDelegate

    func urlSession(_ session: URLSession,
                    dataTask: URLSessionDataTask,
                    didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        if let httpResponse = response as? HTTPURLResponse {
            if let metaintStr = httpResponse.value(forHTTPHeaderField: "icy-metaint"),
               let val = Int(metaintStr), val > 0 {
                metaint = val
                audioBytesRemaining = val
            }

            if let name = httpResponse.value(forHTTPHeaderField: "icy-name") {
                DispatchQueue.main.async { [weak self] in
                    self?.onStationName?(name)
                }
            }
        }
        streamActive = true
        retryCount = 0   // success — reset retry counter
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
                let consume = min(audioBytesRemaining, count - offset)
                offset += consume
                audioBytesRemaining -= consume

            } else if metaLengthRemaining == 0 {
                let metaLenByte = data[offset]
                offset += 1
                metaLengthRemaining = Int(metaLenByte) * 16

                if metaLengthRemaining == 0 {
                    audioBytesRemaining = metaint
                } else {
                    metaBuffer = Data()
                }

            } else {
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
        guard let error else { return }

        let nsErr = error as NSError
        // -999 = cancelled by us, not a real error
        if nsErr.code == NSURLErrorCancelled { return }

        let message = error.localizedDescription
        DispatchQueue.main.async { [weak self] in
            self?.onError?(message)
        }

        // Auto-retry on transient failures (timeout, network down, etc.)
        scheduleRetry()
    }

    // MARK: - Metadata parsing

    private func processMetadata(_ data: Data) {
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

        guard let rawTitle = extractStreamTitle(from: cleaned), !rawTitle.isEmpty else {
            return  // empty chunk — don't overwrite the current display
        }

        // Some stations HTML-encode metadata ("Don&apos;t Stop"); decode
        // here so the menu bar, classifier, and artwork lookup all see
        // the real text.
        let title = HTMLEntities.decode(rawTitle)

        DispatchQueue.main.async { [weak self] in
            self?.onTrackUpdate?(title)
        }
    }

    /// Extracts the value of `StreamTitle='...'` from an ICY metadata string.
    private func extractStreamTitle(from raw: String) -> String? {
        guard let startRange = raw.range(of: "StreamTitle='") else { return nil }
        let searchStart = startRange.upperBound
        let remainder = raw[searchStart...]

        guard let endRange = remainder.range(of: "';") else {
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
