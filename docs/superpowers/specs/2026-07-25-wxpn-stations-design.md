# Add WXPN streams to Linux RadioBar

**Date:** 2026-07-25
**Status:** Approved

## Goal

Add all WXPN (University of Pennsylvania, Philadelphia) streams to the Linux
version of RadioBar. WXPN operates exactly two distinct streams; its other FM
frequencies (e.g. WXPH Harrisburg) are simulcasts, not separate channels.

## Changes

### 1. `linux/radiobar` — `BUILTIN_STATIONS`

Insert two entries directly after KEXP, keeping broadcast/college stations
grouped ahead of internet-only ones:

```python
{"name": "WXPN 88.5 FM",
 "streamURL": "https://wxpnhi.xpn.org/xpnhi",
 "genre": "College/AAA", "websiteURL": "https://xpn.org"},
{"name": "WXPN: XPN2",
 "streamURL": "https://wxpn.xpn.org/xpn2mp3hi",
 "genre": "College/Eclectic", "websiteURL": "https://xpn.org/program/xpn2/"},
```

Both URLs verified live 2026-07-25: direct Icecast, 128 kbps MP3 — the same
style the player already handles for SomaFM. The `WXPN:` prefix on XPN2
follows the existing `SomaFM: <channel>` naming convention for sub-channels.

### 2. Local `~/.config/radiobar/stations.json` (machine-local, not committed)

`BUILTIN_STATIONS` only seeds `stations.json` on first run, so append the same
two entries to the existing local file, inserted after KEXP. Idempotent: skip
any entry whose `name` already exists.

## Testing

- Existing pytest suite passes unchanged (tests compare against
  `rb.BUILTIN_STATIONS` symbolically, not a hardcoded list).
- Live smoke test: `radiobar play "WXPN 88.5 FM"` and confirm status output.

## Out of scope (YAGNI)

- macOS `Sources/Station.swift` (request was Linux-only).
- WQHS (UPenn's separate student-run station).
- Stream-fallback / mirror-URL logic.
