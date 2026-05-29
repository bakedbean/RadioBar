import AVFoundation
import AppKit
import Combine

/// Wraps AVPlayer for internet radio streaming.
///
/// For live radio, "pausing" disconnects from the stream entirely (rather than
/// freezing a buffer position), and "resuming" reconnects fresh — so you always
/// hear the live broadcast, not buffered audio from when you paused.
final class RadioPlayer: NSObject, ObservableObject {

    @Published private(set) var isPlaying = false
    @Published private(set) var currentStation: Station?

    private let player: AVPlayer = {
        let p = AVPlayer()
        p.automaticallyWaitsToMinimizeStalling = true
        p.volume = 0.8
        return p
    }()

    var volume: Float {
        get { player.volume }
        set { player.volume = max(0, min(1, newValue)) }
    }

    var onPlaybackStateChange: ((Bool) -> Void)?
    var onStop: (() -> Void)?      // called when user pauses (disconnects)
    var onResume: (() -> Void)?    // called when user resumes (reconnects)

    override init() {
        super.init()

        player.publisher(for: \.timeControlStatus)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status in
                self?.isPlaying = (status == .playing)
                self?.onPlaybackStateChange?(status == .playing)
            }
            .store(in: &cancellables)
    }

    private var cancellables = Set<AnyCancellable>()

    func play(station: Station) {
        guard let url = station.url else { return }
        currentStation = station
        let item = AVPlayerItem(url: url)
        player.replaceCurrentItem(with: item)
        player.play()
    }

    /// Disconnect from the live stream entirely (don't freeze the buffer).
    func pause() {
        player.pause()
        player.replaceCurrentItem(with: nil)
        onStop?()
    }

    /// Reconnect fresh to the live stream.
    func resume() {
        guard let station = currentStation, let url = station.url else { return }
        let item = AVPlayerItem(url: url)
        player.replaceCurrentItem(with: item)
        player.play()
        onResume?()
    }

    func togglePlayPause() {
        if player.timeControlStatus == .playing {
            pause()
        } else {
            resume()
        }
    }

    func stop() {
        player.pause()
        player.replaceCurrentItem(with: nil)
        currentStation = nil
        onStop?()
    }
}
