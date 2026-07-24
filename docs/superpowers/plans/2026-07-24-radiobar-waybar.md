# RadioBar for waybar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port RadioBar to omarchy/waybar: live track info in the bar, play/pause hotkey, right-click station menu — driven by one Python script controlling mpv.

**Architecture:** A single stdlib-only Python script `linux/radiobar` with subcommands (`status`, `toggle`, `play`, `stop`, `menu`). mpv does all playback and ICY metadata extraction; the script talks to it over a Unix-socket JSON IPC (`$XDG_RUNTIME_DIR/radiobar.sock`). `radiobar status` streams waybar JSON lines; there is no daemon of our own.

**Tech Stack:** Python 3 (stdlib only), mpv, waybar `custom` module, Hyprland bind, walker/fuzzel dmenu mode, pytest for pure-function tests.

**Spec:** `docs/superpowers/specs/2026-07-24-radiobar-waybar-design.md`

## Global Constraints

- Python stdlib only — no pip dependencies in `linux/radiobar` (pytest is dev-only).
- Runtime dependency is exactly one package: `mpv`.
- Stations JSON schema must match the macOS app: keys `name`, `streamURL`, `genre`, `websiteURL`.
- Paths: config `~/.config/radiobar/stations.json`, state `~/.local/state/radiobar/last`, socket `$XDG_RUNTIME_DIR/radiobar.sock` — each overridable via env vars `RADIOBAR_CONFIG_DIR`, `RADIOBAR_STATE_DIR`, `RADIOBAR_SOCK` (this is how tests isolate themselves).
- Bar glyphs: playing `󰐊`, paused `󰏤`, idle `󰐹`. Title truncation at 40 chars.
- Never crash the bar: malformed config falls back to built-ins; closed socket emits idle state.
- All work on branch `waybar-port`; commit after every task; never commit to `main`.
- Waybar/Hyprland live-config edits (Task 8) follow the omarchy skill rules: back up first, edit only `~/.config/`, `omarchy restart waybar` after waybar changes, `hyprctl reload && hyprctl configerrors` after Hyprland changes.

---

### Task 1: Script scaffold + station loading

**Files:**
- Create: `linux/radiobar` (executable)
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Produces: `BUILTIN_STATIONS: list[dict]`; `config_dir() -> Path`; `state_dir() -> Path`; `stations_path() -> Path`; `load_stations() -> list[dict]` (seeds file with built-ins on first call, falls back to built-ins on malformed JSON); `find_station(stations: list[dict], name: str) -> dict | None` (case-insensitive exact name match).

- [ ] **Step 1: Write the failing tests**

Create `linux/test_radiobar.py`:

```python
"""Tests for the radiobar script (loaded from the extensionless file)."""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys


def _load():
    path = pathlib.Path(__file__).parent / "radiobar"
    loader = importlib.machinery.SourceFileLoader("radiobar", str(path))
    spec = importlib.util.spec_from_loader("radiobar", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["radiobar"] = mod
    loader.exec_module(mod)
    return mod


rb = _load()


class TestLoadStations:
    def test_missing_file_seeds_builtins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        stations = rb.load_stations()
        assert stations == rb.BUILTIN_STATIONS
        # file was seeded so users can edit it
        seeded = json.loads((tmp_path / "stations.json").read_text())
        assert seeded == rb.BUILTIN_STATIONS

    def test_valid_file_is_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        mine = [{"name": "X", "streamURL": "https://x/s", "genre": "g",
                 "websiteURL": None}]
        (tmp_path / "stations.json").write_text(json.dumps(mine))
        assert rb.load_stations() == mine

    def test_malformed_file_falls_back_to_builtins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        (tmp_path / "stations.json").write_text("{not json")
        assert rb.load_stations() == rb.BUILTIN_STATIONS

    def test_wrong_shape_falls_back_to_builtins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        (tmp_path / "stations.json").write_text(json.dumps({"nope": 1}))
        assert rb.load_stations() == rb.BUILTIN_STATIONS


class TestFindStation:
    def test_exact_name(self):
        s = rb.find_station(rb.BUILTIN_STATIONS, "FIP")
        assert s is not None and s["streamURL"].endswith("fip-midfi.mp3")

    def test_case_insensitive(self):
        assert rb.find_station(rb.BUILTIN_STATIONS, "fip") is not None

    def test_unknown_returns_none(self):
        assert rb.find_station(rb.BUILTIN_STATIONS, "Nope FM") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eben/RadioBar && python -m pytest linux/test_radiobar.py -v`
Expected: collection error — `FileNotFoundError` for `linux/radiobar` (module doesn't exist yet).

- [ ] **Step 3: Write the scaffold**

Create `linux/radiobar`:

```python
#!/usr/bin/env python3
"""RadioBar for waybar — internet radio with live track info in the bar.

Subcommands: status | toggle | play <name-or-url> | stop | menu
Playback and ICY metadata are delegated to mpv over a JSON IPC socket.
"""
import json
import os
import sys
from pathlib import Path

ICON_PLAY = "\U000f040a"   # 󰐊
ICON_PAUSE = "\U000f03e4"  # 󰏤
ICON_IDLE = "\U000f0439"   # 󰐹
TITLE_LIMIT = 40

BUILTIN_STATIONS = [
    {"name": "WERS 88.9 FM",
     "streamURL": "https://playerservices.streamtheworld.com/api/livestream-redirect/WERSFMAAC.aac",
     "genre": "College/Eclectic", "websiteURL": "https://wers.org"},
    {"name": "KEXP 90.3 FM",
     "streamURL": "https://kexp.streamguys1.com/kexp160.aac",
     "genre": "Eclectic", "websiteURL": "https://kexp.org"},
    {"name": "SomaFM: Groove Salad",
     "streamURL": "https://ice3.somafm.com/groovesalad-256-mp3",
     "genre": "Ambient/Downtempo", "websiteURL": "https://somafm.com"},
    {"name": "SomaFM: Secret Agent",
     "streamURL": "https://ice3.somafm.com/secretagent-128-mp3",
     "genre": "Spy/Lounge", "websiteURL": "https://somafm.com"},
    {"name": "SomaFM: Drone Zone",
     "streamURL": "https://ice3.somafm.com/dronezone-256-mp3",
     "genre": "Ambient/Drone", "websiteURL": "https://somafm.com"},
    {"name": "SomaFM: Lush",
     "streamURL": "https://ice3.somafm.com/lush-128-mp3",
     "genre": "Vocal/Electronic", "websiteURL": "https://somafm.com"},
    {"name": "BBC Radio 6 Music",
     "streamURL": "https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_vlow/ak/bbc_6music.m3u8",
     "genre": "Eclectic", "websiteURL": "https://www.bbc.co.uk/6music"},
    {"name": "NTS Radio 1",
     "streamURL": "https://stream-relay-geo.ntslive.net/stream",
     "genre": "Eclectic", "websiteURL": "https://nts.live"},
    {"name": "FIP",
     "streamURL": "https://icecast.radiofrance.fr/fip-midfi.mp3",
     "genre": "Eclectic", "websiteURL": "https://www.radiofrance.fr/fip"},
    {"name": "Radio Paradise: Main Mix",
     "streamURL": "https://stream.radioparadise.com/aac-320",
     "genre": "Eclectic", "websiteURL": "https://radioparadise.com"},
]


def config_dir() -> Path:
    override = os.environ.get("RADIOBAR_CONFIG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "radiobar"


def state_dir() -> Path:
    override = os.environ.get("RADIOBAR_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))
    return Path(base) / "radiobar"


def stations_path() -> Path:
    return config_dir() / "stations.json"


def load_stations() -> list:
    path = stations_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(BUILTIN_STATIONS, indent=2) + "\n")
        return list(BUILTIN_STATIONS)
    try:
        data = json.loads(path.read_text())
        if (isinstance(data, list) and data
                and all(isinstance(s, dict) and "name" in s and "streamURL" in s
                        for s in data)):
            return data
        raise ValueError("unexpected shape")
    except Exception as exc:
        print(f"radiobar: bad stations.json ({exc}), using built-ins",
              file=sys.stderr)
        return list(BUILTIN_STATIONS)


def find_station(stations: list, name: str):
    for s in stations:
        if s["name"].lower() == name.lower():
            return s
    return None


def main(argv):
    print("radiobar: no command yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Then: `chmod +x linux/radiobar`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): radiobar scaffold with station loading"
```

---

### Task 2: Display formatting (pure functions)

**Files:**
- Modify: `linux/radiobar` (add functions after `find_station`)
- Test: `linux/test_radiobar.py` (append)

**Interfaces:**
- Consumes: constants `ICON_PLAY`, `ICON_PAUSE`, `ICON_IDLE`, `TITLE_LIMIT` from Task 1.
- Produces: `truncate(s: str, limit: int = TITLE_LIMIT) -> str`; `pick_title(icy_title, media_title, station_name) -> str` (skips empty values and URL-looking titles); `waybar_output(*, running: bool, paused: bool = False, icy_title=None, media_title=None, station_name: str = "") -> dict` with keys `text`, `tooltip`, `class`.

- [ ] **Step 1: Write the failing tests** (append to `linux/test_radiobar.py`)

```python
class TestTruncate:
    def test_short_unchanged(self):
        assert rb.truncate("abc") == "abc"

    def test_long_gets_ellipsis_within_limit(self):
        out = rb.truncate("x" * 60)
        assert len(out) == rb.TITLE_LIMIT
        assert out.endswith("…")


class TestPickTitle:
    def test_icy_wins(self):
        assert rb.pick_title("A - B", "media", "St") == "A - B"

    def test_falls_back_to_media_title(self):
        assert rb.pick_title(None, "Show Name", "St") == "Show Name"

    def test_url_media_title_skipped(self):
        # BBC HLS: mpv's media-title is just the stream URL — useless
        assert rb.pick_title(None, "https://a.files.bbci.co.uk/x.m3u8", "BBC 6") == "BBC 6"

    def test_blank_values_skipped(self):
        assert rb.pick_title("  ", "", "St") == "St"


class TestWaybarOutput:
    def test_idle(self):
        out = rb.waybar_output(running=False)
        assert out["class"] == "idle" and out["text"] == rb.ICON_IDLE

    def test_paused_shows_station(self):
        out = rb.waybar_output(running=True, paused=True, station_name="FIP")
        assert out["class"] == "paused"
        assert out["text"] == f"{rb.ICON_PAUSE} FIP"

    def test_playing_shows_title_and_tooltip(self):
        out = rb.waybar_output(running=True, icy_title="Artist - Song",
                               station_name="KEXP 90.3 FM")
        assert out["class"] == "playing"
        assert out["text"] == f"{rb.ICON_PLAY} Artist - Song"
        assert "Artist - Song" in out["tooltip"]
        assert "KEXP 90.3 FM" in out["tooltip"]

    def test_playing_long_title_truncated_in_text_not_tooltip(self):
        long_title = "The Extraordinarily Long Band Name - An Even Longer Song Title"
        out = rb.waybar_output(running=True, icy_title=long_title,
                               station_name="NTS Radio 1")
        assert len(out["text"]) <= len(rb.ICON_PLAY) + 1 + rb.TITLE_LIMIT
        assert long_title in out["tooltip"]
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: Task 1 tests pass; new tests FAIL with `AttributeError: module 'radiobar' has no attribute 'truncate'`.

- [ ] **Step 3: Implement** (add to `linux/radiobar` after `find_station`)

```python
def truncate(s: str, limit: int = TITLE_LIMIT) -> str:
    if len(s) <= limit:
        return s
    return s[:limit - 1].rstrip() + "…"


def pick_title(icy_title, media_title, station_name) -> str:
    for candidate in (icy_title, media_title):
        if not candidate:
            continue
        candidate = candidate.strip()
        if candidate and not candidate.lower().startswith(("http://", "https://")):
            return candidate
    return station_name


def waybar_output(*, running: bool, paused: bool = False, icy_title=None,
                  media_title=None, station_name: str = "") -> dict:
    if not running:
        return {"text": ICON_IDLE, "tooltip": "RadioBar: off", "class": "idle"}
    if paused:
        return {"text": f"{ICON_PAUSE} {truncate(station_name)}",
                "tooltip": f"Paused — {station_name}", "class": "paused"}
    title = pick_title(icy_title, media_title, station_name)
    return {"text": f"{ICON_PLAY} {truncate(title)}",
            "tooltip": f"{title}\n{station_name}".strip(), "class": "playing"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all pass (16 tests).

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): waybar display formatting with title fallback chain"
```

---

### Task 3: Status tracker (mpv events → waybar outputs)

**Files:**
- Modify: `linux/radiobar`
- Test: `linux/test_radiobar.py` (append)

**Interfaces:**
- Consumes: `waybar_output(...)` from Task 2.
- Produces: `OBSERVED_PROPS: list[str]` = `["metadata/by-key/icy-title", "media-title", "pause"]`; class `StatusTracker(station_name: str)` with `handle_event(ev: dict) -> dict | None` (returns a waybar output dict when a relevant property changed, else None) and `output() -> dict`.

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestStatusTracker:
    def test_initial_output_is_playing_station_name(self):
        t = rb.StatusTracker("FIP")
        out = t.output()
        assert out["class"] == "playing" and "FIP" in out["text"]

    def test_icy_title_event_updates_text(self):
        t = rb.StatusTracker("FIP")
        out = t.handle_event({"event": "property-change",
                              "name": "metadata/by-key/icy-title",
                              "data": "Air - La Femme d'Argent"})
        assert out is not None
        assert "Air - La Femme d'Argent" in out["text"]

    def test_pause_event_switches_state(self):
        t = rb.StatusTracker("FIP")
        t.handle_event({"event": "property-change",
                        "name": "metadata/by-key/icy-title", "data": "A - B"})
        out = t.handle_event({"event": "property-change",
                              "name": "pause", "data": True})
        assert out["class"] == "paused"
        out = t.handle_event({"event": "property-change",
                              "name": "pause", "data": False})
        assert out["class"] == "playing" and "A - B" in out["text"]

    def test_irrelevant_events_return_none(self):
        t = rb.StatusTracker("FIP")
        assert t.handle_event({"event": "playback-restart"}) is None
        assert t.handle_event({"request_id": 1, "error": "success"}) is None

    def test_null_icy_data_falls_back(self):
        t = rb.StatusTracker("FIP")
        t.handle_event({"event": "property-change",
                        "name": "metadata/by-key/icy-title", "data": "A - B"})
        out = t.handle_event({"event": "property-change",
                              "name": "metadata/by-key/icy-title", "data": None})
        assert "FIP" in out["text"]
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: new tests FAIL with `AttributeError: ... no attribute 'StatusTracker'`.

- [ ] **Step 3: Implement** (add to `linux/radiobar`)

```python
OBSERVED_PROPS = ["metadata/by-key/icy-title", "media-title", "pause"]


class StatusTracker:
    """Folds mpv property-change events into waybar output dicts."""

    def __init__(self, station_name: str):
        self.station = station_name
        self.icy = None
        self.media = None
        self.paused = False

    def handle_event(self, ev: dict):
        if ev.get("event") != "property-change":
            return None
        name, data = ev.get("name"), ev.get("data")
        if name == "metadata/by-key/icy-title":
            self.icy = data or None
        elif name == "media-title":
            self.media = data or None
        elif name == "pause":
            self.paused = bool(data)
        else:
            return None
        return self.output()

    def output(self) -> dict:
        return waybar_output(running=True, paused=self.paused,
                             icy_title=self.icy, media_title=self.media,
                             station_name=self.station)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all pass (21 tests).

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): status tracker folding mpv events into bar states"
```

---

### Task 4: mpv IPC, launch, last-station state, toggle/play/stop

**Files:**
- Modify: `linux/radiobar`
- Test: `linux/test_radiobar.py` (append)

**Interfaces:**
- Consumes: `load_stations()`, `find_station()` (Task 1).
- Produces: `socket_path() -> Path`; `ipc_command(args: list) -> dict | None` (one-shot command; None if mpv unreachable); `read_last() -> str | None`; `write_last(name: str)`; `launch_mpv(station: dict)`; `cmd_toggle() -> int`; `cmd_play(arg: str) -> int`; `cmd_stop() -> int`. All return POSIX exit codes.

- [ ] **Step 1: Write the failing tests** (append)

```python
import socketserver
import threading


class TestLastStation:
    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        rb.write_last("NTS Radio 1")
        assert rb.read_last() == "NTS Radio 1"

    def test_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        assert rb.read_last() is None


class _FakeMpvHandler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        req = json.loads(line)
        self.server.received.append(req)
        resp = {"request_id": req.get("request_id", 0), "error": "success",
                "data": None}
        self.wfile.write(json.dumps(resp).encode() + b"\n")


class TestIpcCommand:
    def test_sends_command_and_parses_response(self, tmp_path, monkeypatch):
        sock_path = tmp_path / "radiobar.sock"
        monkeypatch.setenv("RADIOBAR_SOCK", str(sock_path))
        server = socketserver.UnixStreamServer(str(sock_path), _FakeMpvHandler)
        server.received = []
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        resp = rb.ipc_command(["cycle", "pause"])
        thread.join(timeout=5)
        server.server_close()
        assert resp is not None and resp["error"] == "success"
        assert server.received[0]["command"] == ["cycle", "pause"]

    def test_no_socket_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_SOCK", str(tmp_path / "absent.sock"))
        assert rb.ipc_command(["cycle", "pause"]) is None

    def test_stale_socket_file_returns_none(self, tmp_path, monkeypatch):
        stale = tmp_path / "stale.sock"
        stale.touch()  # plain file, not a socket → connect fails
        monkeypatch.setenv("RADIOBAR_SOCK", str(stale))
        assert rb.ipc_command(["cycle", "pause"]) is None


class TestToggle:
    def test_running_mpv_gets_cycle_pause(self, monkeypatch):
        sent = []
        monkeypatch.setattr(rb, "ipc_command",
                            lambda args: sent.append(args) or {"error": "success"})
        assert rb.cmd_toggle() == 0
        assert sent == [["cycle", "pause"]]

    def test_cold_start_launches_last_station(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        rb.write_last("FIP")
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        launched = []
        monkeypatch.setattr(rb, "launch_mpv", lambda st: launched.append(st))
        assert rb.cmd_toggle() == 0
        assert launched[0]["name"] == "FIP"

    def test_cold_start_no_history_uses_first_station(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        launched = []
        monkeypatch.setattr(rb, "launch_mpv", lambda st: launched.append(st))
        assert rb.cmd_toggle() == 0
        assert launched[0]["name"] == rb.BUILTIN_STATIONS[0]["name"]


class TestPlay:
    def test_known_station_by_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        launched = []
        monkeypatch.setattr(rb, "launch_mpv", lambda st: launched.append(st))
        assert rb.cmd_play("fip") == 0
        assert launched[0]["name"] == "FIP"

    def test_raw_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        launched = []
        monkeypatch.setattr(rb, "launch_mpv", lambda st: launched.append(st))
        assert rb.cmd_play("https://example.com/stream.mp3") == 0
        assert launched[0]["streamURL"] == "https://example.com/stream.mp3"

    def test_unknown_name_errors(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        assert rb.cmd_play("Nope FM") == 1
        assert "unknown station" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: new tests FAIL with `AttributeError` on `write_last` / `ipc_command` / `cmd_toggle` / `cmd_play`.

- [ ] **Step 3: Implement** (add to `linux/radiobar`; also add `import socket`, `import subprocess` to the imports)

```python
def socket_path() -> Path:
    override = os.environ.get("RADIOBAR_SOCK")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return Path(runtime) / "radiobar.sock"


def ipc_command(args: list):
    """Send one command to mpv, return its response dict, or None if unreachable."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(socket_path()))
            s.sendall(json.dumps({"command": args}).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    return None
                buf += chunk
            for line in buf.split(b"\n"):
                if not line:
                    continue
                resp = json.loads(line)
                if "error" in resp:
                    return resp
            return None
    except (OSError, ValueError):
        return None


def last_path() -> Path:
    return state_dir() / "last"


def read_last():
    try:
        name = last_path().read_text().strip()
        return name or None
    except OSError:
        return None


def write_last(name: str):
    last_path().parent.mkdir(parents=True, exist_ok=True)
    last_path().write_text(name + "\n")


def launch_mpv(station: dict):
    sock = socket_path()
    sock.unlink(missing_ok=True)
    subprocess.Popen(
        ["mpv", "--no-video", f"--input-ipc-server={sock}",
         "--stream-lavf-o=reconnect_streamed=1,reconnect_delay_max=10",
         station["streamURL"]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    write_last(station["name"])


def cmd_toggle() -> int:
    if ipc_command(["cycle", "pause"]) is not None:
        return 0
    stations = load_stations()
    station = None
    last = read_last()
    if last:
        station = find_station(stations, last)
    if station is None:
        station = stations[0]
    launch_mpv(station)
    return 0


def cmd_play(arg: str) -> int:
    if arg.lower().startswith(("http://", "https://")):
        station = {"name": arg, "streamURL": arg, "genre": "", "websiteURL": None}
    else:
        station = find_station(load_stations(), arg)
        if station is None:
            print(f"radiobar: unknown station: {arg}", file=sys.stderr)
            return 1
    ipc_command(["quit"])
    launch_mpv(station)
    return 0


def cmd_stop() -> int:
    ipc_command(["quit"])
    return 0
```

Note: `cmd_play` for a raw URL stores the URL as the station name; `read_last` + `find_station` won't match it on a later cold toggle, so toggle falls back to the first station. That is acceptable and matches the spec's "last-played **station**" wording.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all pass (31 tests).

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): mpv IPC, launch, and toggle/play/stop commands"
```

---

### Task 5: `status` loop and CLI dispatch

**Files:**
- Modify: `linux/radiobar` (add `cmd_status`, `watch`, `emit`; replace `main`)
- Test: `linux/test_radiobar.py` (append)

**Interfaces:**
- Consumes: `StatusTracker`, `OBSERVED_PROPS` (Task 3); `socket_path`, `read_last` (Task 4); `waybar_output` (Task 2).
- Produces: `emit(d: dict)` (one compact JSON line to stdout, flushed); `watch(sock)` (observes props, emits on every change, raises `OSError` when the socket closes); `cmd_status()` (infinite loop: connect-or-idle, 2s re-poll); `main(argv) -> int` dispatching `status|toggle|play|stop|menu`.

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestEmit:
    def test_one_compact_json_line(self, capsys):
        rb.emit({"text": "x", "tooltip": "t", "class": "playing"})
        out = capsys.readouterr().out
        assert out.endswith("\n") and out.count("\n") == 1
        assert json.loads(out) == {"text": "x", "tooltip": "t", "class": "playing"}


class TestWatch:
    def test_observes_props_emits_updates_and_raises_on_close(
            self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        rb.write_last("FIP")
        sock_path = tmp_path / "radiobar.sock"

        received = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for _ in rb.OBSERVED_PROPS:
                    received.append(json.loads(self.rfile.readline()))
                ev = {"event": "property-change",
                      "name": "metadata/by-key/icy-title", "data": "A - B"}
                self.wfile.write(json.dumps(ev).encode() + b"\n")
                # then close the connection → watch must raise OSError

        server = socketserver.UnixStreamServer(str(sock_path), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        import socket as socket_mod
        client = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        client.connect(str(sock_path))
        try:
            import pytest
            with pytest.raises(OSError):
                rb.watch(client)
        finally:
            client.close()
            thread.join(timeout=5)
            server.server_close()

        assert [r["command"][2] for r in received] == rb.OBSERVED_PROPS
        lines = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
        # initial state, then the icy-title update
        assert any("A - B" in l["text"] for l in lines)


class TestMainDispatch:
    def test_unknown_command_usage(self, capsys):
        assert rb.main(["bogus"]) == 2
        assert "usage" in capsys.readouterr().err.lower()

    def test_no_command_usage(self, capsys):
        assert rb.main([]) == 2

    def test_toggle_dispatches(self, monkeypatch):
        monkeypatch.setattr(rb, "cmd_toggle", lambda: 0)
        assert rb.main(["toggle"]) == 0

    def test_play_requires_arg(self, capsys):
        assert rb.main(["play"]) == 2
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: new tests FAIL (`emit` / `watch` missing; `main(["bogus"])` returns 1 not 2).

- [ ] **Step 3: Implement** (add to `linux/radiobar`; add `import socket` usage and `import time`; replace the stub `main`)

```python
def emit(d: dict):
    print(json.dumps(d, separators=(",", ":")), flush=True)


def watch(sock):
    """Observe mpv properties on an open socket; emit bar updates until it closes."""
    tracker = StatusTracker(read_last() or "")
    for i, prop in enumerate(OBSERVED_PROPS, start=1):
        sock.sendall(json.dumps({"command": ["observe_property", i, prop]})
                     .encode() + b"\n")
    emit(tracker.output())
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("mpv socket closed")
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            out = tracker.handle_event(ev)
            if out is not None:
                emit(out)


def cmd_status() -> int:
    while True:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(str(socket_path()))
        except OSError:
            s.close()
            emit(waybar_output(running=False))
            time.sleep(2)
            continue
        try:
            watch(s)
        except OSError:
            pass
        finally:
            s.close()
        emit(waybar_output(running=False))
        time.sleep(2)


USAGE = "usage: radiobar status|toggle|play <name-or-url>|stop|menu"


def main(argv) -> int:
    if not argv:
        print(USAGE, file=sys.stderr)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "status":
        return cmd_status()
    if cmd == "toggle":
        return cmd_toggle()
    if cmd == "play":
        if len(args) != 1:
            print(USAGE, file=sys.stderr)
            return 2
        return cmd_play(args[0])
    if cmd == "stop":
        return cmd_stop()
    if cmd == "menu":
        return cmd_menu()
    print(USAGE, file=sys.stderr)
    return 2
```

(`cmd_menu` does not exist until Task 6 — Python only resolves it at call time, so dispatch to it is safe to write now and the tests here never call it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all pass (37 tests).

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): status event loop and CLI dispatch"
```

---

### Task 6: `menu` command (walker/fuzzel)

**Files:**
- Modify: `linux/radiobar`
- Test: `linux/test_radiobar.py` (append)

**Interfaces:**
- Consumes: `load_stations`, `cmd_play` (Tasks 1, 4).
- Produces: `find_menu_cmd(which=shutil.which) -> list[str] | None` (walker preferred, fuzzel fallback); `cmd_menu(run=subprocess.run) -> int` (shows station names, plays selection; empty selection is a no-op; no menu tool → `notify-send` + exit 1).

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestFindMenuCmd:
    def test_prefers_walker(self):
        which = lambda name: "/usr/bin/" + name  # both installed
        assert rb.find_menu_cmd(which) == ["walker", "--dmenu"]

    def test_falls_back_to_fuzzel(self):
        which = lambda name: "/usr/bin/fuzzel" if name == "fuzzel" else None
        assert rb.find_menu_cmd(which) == ["fuzzel", "-d"]

    def test_none_when_neither(self):
        assert rb.find_menu_cmd(lambda name: None) is None


class TestCmdMenu:
    def _fake_run(self, stdout):
        calls = []

        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            class R:
                pass
            r = R()
            r.stdout = stdout
            r.returncode = 0
            return r
        return run, calls

    def test_selection_is_played(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        played = []
        monkeypatch.setattr(rb, "cmd_play", lambda name: played.append(name) or 0)
        monkeypatch.setattr(rb, "find_menu_cmd",
                            lambda which=None: ["walker", "--dmenu"])
        run, calls = self._fake_run("FIP\n")
        assert rb.cmd_menu(run=run) == 0
        assert played == ["FIP"]
        # the station list was piped in
        assert "FIP" in calls[0][1]["input"]

    def test_empty_selection_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        played = []
        monkeypatch.setattr(rb, "cmd_play", lambda name: played.append(name) or 0)
        monkeypatch.setattr(rb, "find_menu_cmd",
                            lambda which=None: ["walker", "--dmenu"])
        run, _ = self._fake_run("")
        assert rb.cmd_menu(run=run) == 0
        assert played == []

    def test_no_menu_tool_notifies_and_fails(self, monkeypatch):
        monkeypatch.setattr(rb, "find_menu_cmd", lambda which=None: None)
        notified = []
        run, _ = self._fake_run("")

        def run_capture(cmd, **kwargs):
            notified.append(cmd)
            return run(cmd, **kwargs)
        assert rb.cmd_menu(run=run_capture) == 1
        assert notified and notified[0][0] == "notify-send"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: new tests FAIL with `AttributeError: ... no attribute 'find_menu_cmd'`.

- [ ] **Step 3: Implement** (add to `linux/radiobar`; add `import shutil` to imports)

```python
def find_menu_cmd(which=shutil.which):
    if which("walker"):
        return ["walker", "--dmenu"]
    if which("fuzzel"):
        return ["fuzzel", "-d"]
    return None


def cmd_menu(run=subprocess.run) -> int:
    menu = find_menu_cmd()
    if menu is None:
        run(["notify-send", "RadioBar",
             "No menu tool found (install walker or fuzzel)"])
        return 1
    stations = load_stations()
    names = "\n".join(s["name"] for s in stations) + "\n"
    result = run(menu, input=names, capture_output=True, text=True)
    choice = result.stdout.strip()
    if not choice:
        return 0
    return cmd_play(choice)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all pass (43 tests).

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): right-click station menu via walker/fuzzel"
```

---

### Task 7: Config snippets and linux README

**Files:**
- Create: `linux/waybar-snippet.jsonc`
- Create: `linux/style-snippet.css`
- Create: `linux/README.md`
- Modify: `README.md` (add a short "Linux (waybar)" section link)

- [ ] **Step 1: Create `linux/waybar-snippet.jsonc`**

```jsonc
// Add "custom/radio" to one of the modules arrays in ~/.config/waybar/config.jsonc
// (e.g. "modules-right"), then paste this block among the module definitions:
"custom/radio": {
  "exec": "radiobar status",
  "return-type": "json",
  "on-click": "radiobar toggle",
  "on-click-right": "radiobar menu",
  "tooltip": true
}
```

- [ ] **Step 2: Create `linux/style-snippet.css`**

```css
/* Append to ~/.config/waybar/style.css */
#custom-radio {
  padding: 0 10px;
}

#custom-radio.playing {
  color: @foreground;
}

#custom-radio.paused,
#custom-radio.idle {
  opacity: 0.5;
}
```

- [ ] **Step 3: Create `linux/README.md`**

```markdown
# RadioBar for waybar (omarchy / Hyprland)

The Linux port of RadioBar: live track info in your waybar, play/pause from a
hotkey, right-click to switch stations. One script + mpv, no daemon.

## Requirements

- `mpv` (`sudo pacman -S mpv`)
- waybar with a Nerd Font (omarchy default works)
- walker or fuzzel for the station menu (omarchy ships walker)
- Python 3

## Install

    cp linux/radiobar ~/.local/bin/radiobar
    chmod +x ~/.local/bin/radiobar

**Waybar** — merge `linux/waybar-snippet.jsonc` into
`~/.config/waybar/config.jsonc` (add `"custom/radio"` to a modules array and
paste the module block), append `linux/style-snippet.css` to
`~/.config/waybar/style.css`, then restart waybar (`omarchy restart waybar`
on omarchy).

**Hotkey (Hyprland)** — add to `~/.config/hypr/bindings.conf`:

    bindd = SUPER SHIFT, R, RadioBar play/pause, exec, radiobar toggle

## Usage

| Action | How |
|---|---|
| Play/pause | Left-click the module, or SUPER+SHIFT+R |
| Switch station | Right-click the module |
| Add a station | Edit `~/.config/radiobar/stations.json` (same schema as the macOS app) |
| Stop | `radiobar stop` |

The module shows `󰐊 Artist – Song` while playing (full title in the tooltip),
`󰏤 Station` when paused, and a dim `󰐹` when off.

## How it works

mpv plays the stream and parses ICY (Shoutcast/Icecast) metadata natively.
`radiobar status` subscribes to mpv's JSON IPC socket
(`$XDG_RUNTIME_DIR/radiobar.sock`), observes `icy-title`/`pause`, and prints a
waybar JSON line on every change — so track changes hit the bar within a
second. Streams without ICY metadata (e.g. BBC's HLS) fall back to the
station name.

## Tests

    python -m pytest linux/test_radiobar.py
```

- [ ] **Step 4: Add a section to the top-level `README.md`** (after the Install section)

```markdown
## Linux (waybar/Hyprland)

RadioBar also runs on Linux as a waybar module driven by mpv — same station
list, same live track info in the bar. See [linux/README.md](linux/README.md).
```

- [ ] **Step 5: Commit**

```bash
git add linux/waybar-snippet.jsonc linux/style-snippet.css linux/README.md README.md
git commit -m "docs(linux): waybar/hyprland config snippets and install guide"
```

---

### Task 8: Install locally and verify end-to-end (this machine)

This task touches live omarchy config — follow omarchy skill rules: back up each file before editing, edit only `~/.config/`, restart waybar afterward.

**Files (outside repo):**
- Create: `~/.local/bin/radiobar` (copy)
- Modify: `~/.config/waybar/config.jsonc` (backup first)
- Modify: `~/.config/waybar/style.css` (backup first)
- Modify: `~/.config/hypr/bindings.conf` (backup first)

- [ ] **Step 1: Install script and check runtime deps**

```bash
cp linux/radiobar ~/.local/bin/radiobar && chmod +x ~/.local/bin/radiobar
command -v mpv || sudo pacman -S --noconfirm mpv
command -v walker
```

Expected: all three commands resolve.

- [ ] **Step 2: Smoke-test the CLI without waybar**

```bash
radiobar play "SomaFM: Groove Salad"
sleep 5
timeout 6 radiobar status | head -3
```

Expected: audio audible; status lines show `{"text":"󰐊 <artist - song>","class":"playing",...}` with a real ICY title within a few seconds.

- [ ] **Step 3: Verify toggle + BBC fallback + stop**

```bash
radiobar toggle && timeout 3 radiobar status | head -1   # paused state
radiobar toggle
radiobar play "BBC Radio 6 Music" && sleep 8 && timeout 3 radiobar status | head -1
radiobar stop && timeout 3 radiobar status | head -1     # idle state
```

Expected: paused line has `"class":"paused"`; BBC line shows `󰐊 BBC Radio 6 Music` (no ICY → station-name fallback); stopped line has `"class":"idle"`.

- [ ] **Step 4: Wire up waybar (backup, edit, restart)**

```bash
cp ~/.config/waybar/config.jsonc ~/.config/waybar/config.jsonc.bak.$(date +%s)
cp ~/.config/waybar/style.css ~/.config/waybar/style.css.bak.$(date +%s)
```

Then with the Edit tool: add `"custom/radio"` to the `modules-right` array in `~/.config/waybar/config.jsonc`, paste the module block from `linux/waybar-snippet.jsonc` among the module definitions, and append `linux/style-snippet.css` to `~/.config/waybar/style.css`. Then:

```bash
omarchy restart waybar
```

Expected: waybar restarts; module visible (dim `󰐹` if stopped).

- [ ] **Step 5: Wire up the hotkey**

```bash
cp ~/.config/hypr/bindings.conf ~/.config/hypr/bindings.conf.bak.$(date +%s)
```

Append to `~/.config/hypr/bindings.conf` (SUPER+SHIFT+R verified unbound on this machine):

```
bindd = SUPER SHIFT, R, RadioBar play/pause, exec, radiobar toggle
```

```bash
hyprctl reload && hyprctl configerrors
```

Expected: `configerrors` reports none. Pressing SUPER+SHIFT+R starts the last station; track title appears in the bar; left-click pauses; right-click opens the walker station menu.

- [ ] **Step 6: Run the full test suite one last time and commit any fixes**

```bash
python -m pytest linux/test_radiobar.py -v
```

Expected: all pass. If manual verification exposed fixes, commit them:

```bash
git add -A linux/ && git commit -m "fix(linux): adjustments from end-to-end verification"
```

---

### Task 9: Push branch and open PR

- [ ] **Step 1: Push**

```bash
git push -u origin waybar-port
```

- [ ] **Step 2: Open PR** (per user's global git rules — never merge to main directly)

```bash
gh pr create --title "Linux port: RadioBar as a waybar module (mpv-driven)" --body "$(cat <<'EOF'
## Summary
- Ports RadioBar to Linux (omarchy/Hyprland/waybar) as a single stdlib-Python script driving mpv
- Live ICY track info in the bar via mpv's JSON IPC (replaces the macOS MetadataParser)
- Play/pause hotkey (Hyprland bind), left-click toggle, right-click walker/fuzzel station menu
- Reuses the exact stations.json schema from the macOS app, seeded with the same 10 stations

## Design
Spec: docs/superpowers/specs/2026-07-24-radiobar-waybar-design.md
Plan: docs/superpowers/plans/2026-07-24-radiobar-waybar.md

## Test plan
- [x] 43 pytest unit tests over the pure logic (formatting, fallback chain, stations, IPC, menu)
- [x] Manual end-to-end on omarchy: SomaFM (ICY), BBC HLS (no-ICY fallback), toggle/menu/hotkey
EOF
)"
```

Expected: PR URL printed.

---

## Self-Review Notes

- **Spec coverage:** status/toggle/play/stop/menu → Tasks 4–6; display states & fallback chain → Tasks 2–3; stations schema + seeding + malformed fallback → Task 1; waybar/hyprland/css snippets + install docs → Task 7; live install with omarchy safety rules + manual ICY/HLS verification → Task 8; branch/PR rules → Task 9. Out-of-scope items (volume, MPRIS, station UI) have no tasks, as specified.
- **Type consistency:** `waybar_output` keyword-only signature is identical at every call site (Tasks 2, 3, 5); `ipc_command` returns `dict | None` and every caller treats `None` as "mpv not running"; `find_menu_cmd(which=...)` / `cmd_menu(run=...)` injection points match their tests.
- **Placeholder scan:** every code step contains complete code; expected test counts stated per task (7 → 16 → 21 → 31 → 37 → 43).
