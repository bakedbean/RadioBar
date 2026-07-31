# RadioBar

A minimal macOS menubar app for streaming internet radio, with live track info displayed directly in the menubar — no dropdown required.

## Why?

Most menubar radio apps (Triode, etc.) hide track info behind a dropdown. RadioBar parses ICY (Shoutcast/Icecast) metadata from the raw stream bytes and shows the current song right in your menubar.

## Features

- Live track info in the menubar title (artist – song)
- 12 built-in stations (WERS, KEXP, WXPN, SomaFM, BBC 6, NTS, FIP, Radio Paradise)
- Add your own stations via stream URL
- Play/pause, volume control
- Global play/pause hotkey: <kbd>⌃</kbd><kbd>⌥</kbd><kbd>⌘</kbd><kbd>Space</kbd> (works from any app)
- No Dock icon — menubar only
- Auto-adapts to light/dark mode

## Built-in Stations

| Station | Genre |
|---------|-------|
| WERS 88.9 FM | College/Eclectic |
| KEXP 90.3 FM | Eclectic |
| WXPN 88.5 FM | College/AAA |
| WXPN: XPN2 | College/Eclectic |
| SomaFM: Groove Salad | Ambient/Downtempo |
| SomaFM: Secret Agent | Spy/Lounge |
| SomaFM: Drone Zone | Ambient/Drone |
| SomaFM: Lush | Vocal/Electronic |
| BBC Radio 6 Music | Eclectic |
| NTS Radio 1 | Eclectic |
| FIP | Eclectic |
| Radio Paradise: Main Mix | Eclectic |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| <kbd>⌃</kbd><kbd>⌥</kbd><kbd>⌘</kbd><kbd>Space</kbd> | Toggle play/pause from any app |

The play/pause hotkey is registered system-wide, so it works even when RadioBar isn't the focused app.

## Requirements

- macOS 14.0 (Sonoma) or later
- Apple Silicon or Intel

## Install

### Download

Download the latest `RadioBar.app` from [Releases](https://github.com/bakedbean/RadioBar/releases) and drag it to your Applications folder.

### Build from source

```bash
git clone https://github.com/bakedbean/RadioBar.git
cd RadioBar
make build
open build/RadioBar.app
```

## Linux (waybar/Hyprland)

RadioBar also runs on Linux as a waybar module driven by mpv — same station
list, same live track info in the bar. See [linux/README.md](linux/README.md).

## How It Works

Internet radio streams (Shoutcast/Icecast) embed song metadata inside the audio bytes using the ICY protocol. AVPlayer can play the audio but hides the raw bytes.

RadioBar opens a second, parallel connection to the same stream URL — one for audio (AVPlayer), one for metadata (raw URLSession). The metadata parser reads the `icy-metaint` interval from stream headers, skips audio chunks, and extracts `StreamTitle='Artist - Song'` strings from the in-band metadata blocks.

No external dependencies. Pure Swift + AppKit.

## License

MIT
