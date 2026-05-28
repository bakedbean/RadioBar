import AVFoundation
import AppKit
import Combine

/// Wraps AVPlayer for internet radio streaming.
/// Manages play/pause/stop and exposes volume control.
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
    var onNowPlaying: ((String?) -> Void)?

    override init() {
        super.init()

        // Observe AVPlayer status
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

    func pause() {
        player.pause()
    }

    func resume() {
        player.play()
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
    }
}
