import AppKit
import Combine

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {

    // MARK: - Dependencies

    private let player = RadioPlayer()
    private let metadataParser = MetadataParser()
    private let artworkFetcher = ArtworkFetcher()
    private var stations: [Station] = StationStore.load()
    private var cancellables = Set<AnyCancellable>()

    // MARK: - Status item

    private var statusItem: NSStatusItem!

    // MARK: - Menu items (rebuilt when state changes)

    private weak var nowPlayingItem: NSMenuItem?
    private weak var stationLabelItem: NSMenuItem?
    private weak var artworkImageView: NSImageView?
    private weak var playPauseItem: NSMenuItem?
    private weak var volumeSlider: NSSlider?

    // MARK: - NSApplicationDelegate

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupStatusItem()
        setupCallbacks()
        setMenubarTitle(defaultText: "RadioBar")

        // Load last station and auto-play if the user wants
        // (opted out for v1 — manual play)
    }

    // MARK: - Status item

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            // Radio icon from SF Symbols — template image auto-adapts to light/dark mode
            if let icon = NSImage(systemSymbolName: "antenna.radiowaves.left.and.right",
                                  accessibilityDescription: "RadioBar") {
                icon.isTemplate = true
                button.image = icon
                button.imagePosition = .imageLeading
                // Size the icon to match the menubar text height
                if let font = button.font {
                    let size = font.pointSize + 2
                    button.image?.size = NSSize(width: size, height: size)
                }
            }
            button.title = "RadioBar"
            button.target = self
            button.action = #selector(statusItemClicked)
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        buildMenu()
    }

    private func setMenubarTitle(_ title: String?) {
        let text: String
        if let title, !title.isEmpty {
            let truncated: String
            if title.count > 48 {
                truncated = String(title.prefix(47)) + "…"
            } else {
                truncated = title
            }
            text = truncated
        } else if let station = player.currentStation {
            text = station.name
        } else {
            text = "RadioBar"
        }
        statusItem.button?.title = text
    }

    private func setMenubarTitle(defaultText: String) {
        statusItem.button?.title = defaultText
    }

    // MARK: - Menu

    private func buildMenu() {
        let menu = NSMenu()
        menu.autoenablesItems = false

        // --- Album artwork (larger, in dropdown) ---
        let artworkItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        artworkItem.isEnabled = false
        let artworkContainer = NSView(frame: NSRect(x: 0, y: 0, width: 200, height: 200))
        let imageView = NSImageView(frame: NSRect(x: 4, y: 4, width: 192, height: 192))
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.wantsLayer = true
        imageView.layer?.cornerRadius = 6
        imageView.layer?.masksToBounds = true
        artworkContainer.addSubview(imageView)
        artworkItem.view = artworkContainer
        menu.addItem(artworkItem)
        artworkImageView = imageView

        // --- Now Playing info (disabled, display only) ---
        let nowPlaying = NSMenuItem(title: "Not Playing", action: nil, keyEquivalent: "")
        nowPlaying.isEnabled = false
        nowPlayingItem = nowPlaying
        menu.addItem(nowPlaying)

        let stationLabel = NSMenuItem(title: "No station selected", action: nil, keyEquivalent: "")
        stationLabel.isEnabled = false
        stationLabelItem = stationLabel
        menu.addItem(stationLabel)

        menu.addItem(.separator())

        // --- Play / Pause ---
        let playPause = NSMenuItem(title: "▶  Play", action: #selector(togglePlayPause), keyEquivalent: " ")
        playPause.keyEquivalentModifierMask = []
        playPause.target = self
        playPauseItem = playPause
        menu.addItem(playPause)

        // --- Volume slider ---
        let volumeItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        let slider = NSSlider(value: Double(player.volume), minValue: 0, maxValue: 1,
                              target: self, action: #selector(volumeChanged(_:)))
        slider.frame = NSRect(x: 0, y: 0, width: 160, height: 20)
        slider.isContinuous = true
        let sliderView = NSView(frame: NSRect(x: 0, y: 0, width: 184, height: 28))
        slider.frame.origin = NSPoint(x: 12, y: 4)
        sliderView.addSubview(slider)
        volumeItem.view = sliderView
        volumeSlider = slider
        menu.addItem(volumeItem)

        menu.addItem(.separator())

        // --- Stations submenu ---
        let stationsMenuItem = NSMenuItem(title: "Stations", action: nil, keyEquivalent: "")
        let stationsMenu = NSMenu()
        buildStationsSubmenu(into: stationsMenu)
        stationsMenuItem.submenu = stationsMenu
        menu.addItem(stationsMenuItem)

        menu.addItem(.separator())

        // --- Copy track info ---
        let copyItem = NSMenuItem(title: "Copy Track Info", action: #selector(copyTrackInfo), keyEquivalent: "c")
        copyItem.keyEquivalentModifierMask = [.command]
        copyItem.target = self
        menu.addItem(copyItem)

        // --- Refresh metadata ---
        let refreshItem = NSMenuItem(title: "Refresh Metadata", action: #selector(refreshMetadata), keyEquivalent: "r")
        refreshItem.keyEquivalentModifierMask = [.command, .shift]
        refreshItem.target = self
        menu.addItem(refreshItem)

        menu.addItem(.separator())

        // --- Quit ---
        let quitItem = NSMenuItem(title: "Quit RadioBar", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.keyEquivalentModifierMask = [.command]
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem.menu = menu
        menu.delegate = self
    }

    // MARK: - NSMenuDelegate

    func menuWillOpen(_ menu: NSMenu) {
        rebuildStationsSubmenu()
        refreshPlayPauseUI()
    }

    private func buildStationsSubmenu(into menu: NSMenu) {
        for station in stations {
            let item = NSMenuItem(title: station.name, action: #selector(selectStation(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = station
            if station.id == player.currentStation?.id {
                item.state = .on
            }
            item.indentationLevel = 0
            menu.addItem(item)
        }
        menu.addItem(.separator())
        let addItem = NSMenuItem(title: "Add Station...", action: #selector(addStation), keyEquivalent: "")
        addItem.target = self
        menu.addItem(addItem)
    }

    private func refreshNowPlayingUI(track: String?) {
        if let track, !track.isEmpty {
            nowPlayingItem?.title = "Now Playing: \(track)"
            nowPlayingItem?.isEnabled = false
        } else if let station = player.currentStation {
            nowPlayingItem?.title = "Now Playing: \(station.name)"
            nowPlayingItem?.isEnabled = false
        } else {
            nowPlayingItem?.title = "Not Playing"
            nowPlayingItem?.isEnabled = false
        }

        if let station = player.currentStation {
            stationLabelItem?.title = station.name
        } else {
            stationLabelItem?.title = "No station selected"
        }

        setMenubarTitle(track)
    }

    private func refreshPlayPauseUI() {
        if player.isPlaying {
            playPauseItem?.title = "⏸  Pause"
        } else if player.currentStation != nil {
            playPauseItem?.title = "▶  Resume"
        } else {
            playPauseItem?.title = "▶  Play"
        }
    }

    private func fetchArtwork(for track: String) {
        artworkFetcher.fetch(artistSong: track) { [weak self] image in
            guard let self, let image else { return }
            // Larger version in dropdown
            self.artworkImageView?.image = image

            // Small thumbnail in menubar (replace radio icon)
            let thumb = self.thumbnail(from: image, size: 18)
            self.statusItem.button?.image = thumb
        }
    }

    /// Create a square thumbnail of the given size from an image.
    private func thumbnail(from image: NSImage, size: CGFloat) -> NSImage {
        let thumb = NSImage(size: NSSize(width: size, height: size))
        thumb.lockFocus()
        let rect = NSRect(x: 0, y: 0, width: size, height: size)
        let path = NSBezierPath(roundedRect: rect, xRadius: 3, yRadius: 3)
        path.addClip()
        image.draw(in: rect, from: .zero, operation: .copy, fraction: 1.0)
        thumb.unlockFocus()
        thumb.isTemplate = false
        return thumb
    }

    // MARK: - Callbacks

    private func setupCallbacks() {
        // Player state → update play/pause menu item
        player.onPlaybackStateChange = { [weak self] _ in
            DispatchQueue.main.async {
                self?.refreshPlayPauseUI()
            }
        }

        // Metadata → update menubar title + now-playing label + artwork
        metadataParser.onTrackUpdate = { [weak self] track in
            DispatchQueue.main.async {
                self?.refreshNowPlayingUI(track: track)
                if let track, !track.isEmpty {
                    self?.fetchArtwork(for: track)
                }
            }
        }

        metadataParser.onStationName = { [weak self] name in
            guard let name else { return }
            DispatchQueue.main.async {
                // Only use ICY name as fallback — prefer the user's station name
                if self?.player.currentStation == nil {
                    self?.stationLabelItem?.title = name
                }
                // Don't overwrite the menubar if we already have track info
                if self?.statusItem.button?.title == "RadioBar" {
                    self?.setMenubarTitle(name)
                }
            }
        }

        metadataParser.onError = { [weak self] msg in
            DispatchQueue.main.async {
                self?.nowPlayingItem?.title = "Metadata error: \(msg)"
            }
        }

        // Pause → disconnect metadata; resume → reconnect
        player.onStop = { [weak self] in
            self?.metadataParser.disconnect()
        }
        player.onResume = { [weak self] in
            if let station = self?.player.currentStation, let url = station.url {
                self?.metadataParser.connect(to: url)
            }
        }
    }

    // MARK: - Actions

    @objc private func statusItemClicked() {
        // Rebuild stations submenu to update checkmarks
        rebuildStationsSubmenu()
        refreshPlayPauseUI()
    }

    private func rebuildStationsSubmenu() {
        guard let stationsItem = statusItem.menu?.item(withTitle: "Stations"),
              let submenu = stationsItem.submenu else { return }
        submenu.removeAllItems()
        buildStationsSubmenu(into: submenu)
    }

    @objc private func selectStation(_ sender: NSMenuItem) {
        guard let station = sender.representedObject as? Station else { return }
        player.play(station: station)

        // Connect metadata parser to the same stream
        if let url = station.url {
            metadataParser.connect(to: url)
        }

        setMenubarTitle(station.name)
        stationLabelItem?.title = station.name
        nowPlayingItem?.title = "Loading..."
        refreshPlayPauseUI()
    }

    @objc private func togglePlayPause() {
        if player.currentStation == nil {
            // Nothing loaded — pick the first station
            if let first = stations.first {
                selectStationByReference(first)
            }
            return
        }
        player.togglePlayPause()
    }

    private func selectStationByReference(_ station: Station) {
        player.play(station: station)
        if let url = station.url {
            metadataParser.connect(to: url)
        }
        setMenubarTitle(station.name)
        stationLabelItem?.title = station.name
        nowPlayingItem?.title = "Loading..."
        refreshPlayPauseUI()
    }

    @objc private func addStation() {
        let alert = NSAlert()
        alert.messageText = "Add Radio Station"
        alert.informativeText = "Enter the station name and stream URL."
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Add")
        alert.addButton(withTitle: "Cancel")

        // Build the form fields
        let stack = NSStackView(frame: NSRect(x: 0, y: 0, width: 320, height: 60))
        stack.orientation = .vertical
        stack.spacing = 8

        let nameField = NSTextField(frame: NSRect(x: 0, y: 30, width: 320, height: 24))
        nameField.placeholderString = "Station name (e.g. WERS 88.9 FM)"
        nameField.bezelStyle = .roundedBezel
        stack.addArrangedSubview(nameField)

        let urlField = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        urlField.placeholderString = "Stream URL (https://...)"
        urlField.bezelStyle = .roundedBezel
        stack.addArrangedSubview(urlField)

        alert.accessoryView = stack
        alert.window.initialFirstResponder = nameField

        let response = alert.runModal()
        guard response == .alertFirstButtonReturn else { return }
        let name = nameField.stringValue.trimmingCharacters(in: .whitespaces)
        let urlString = urlField.stringValue.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !urlString.isEmpty, URL(string: urlString) != nil else { return }

        let station = Station(name: name, streamURL: urlString, genre: "", websiteURL: nil)
        self.stations.append(station)
        StationStore.save(self.stations)
    }

    @objc private func volumeChanged(_ sender: NSSlider) {
        player.volume = Float(sender.doubleValue)
    }

    @objc private func copyTrackInfo() {
        let info: String
        if let station = player.currentStation {
            let track = nowPlayingItem?.title
                .replacingOccurrences(of: "Now Playing: ", with: "") ?? station.name
            info = "\(track) — \(station.name)"
        } else {
            info = "RadioBar — not playing"
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(info, forType: .string)
    }

    @objc private func refreshMetadata() {
        guard let station = player.currentStation, let url = station.url else { return }
        nowPlayingItem?.title = "Refreshing metadata..."
        metadataParser.disconnect()
        metadataParser.connect(to: url)
    }

    @objc private func quitApp() {
        player.stop()
        metadataParser.disconnect()
        NSApplication.shared.terminate(nil)
    }
}
