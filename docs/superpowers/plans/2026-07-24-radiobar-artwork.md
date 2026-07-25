# RadioBar Artwork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Album artwork for the playing track — iTunes lookup (port of macOS ArtworkFetcher), thumbnail in waybar via the image module, mako notification with cover + release year on track change.

**Architecture:** All code lives in `linux/radiobar`. Pure fetch/parse/cache functions + an `ArtworkWorker` (daemon-thread dispatch, injected collaborators) hooked into the existing `watch` loop on title transitions. Publishing = copy jpg to `$XDG_RUNTIME_DIR/radiobar-art.jpg` + `pkill -RTMIN+6 waybar`; notification via `notify-send`.

**Tech Stack:** Python stdlib (urllib, hashlib, threading), waybar `image` module, mako/notify-send.

**Spec:** `docs/superpowers/specs/2026-07-24-radiobar-artwork-design.md`

## Global Constraints

- Python stdlib only in `linux/radiobar`.
- Env overrides (tests rely on them): `RADIOBAR_CACHE_DIR` (else `$XDG_CACHE_HOME/radiobar`, else `~/.cache/radiobar`), `RADIOBAR_ART_PATH` (else `$XDG_RUNTIME_DIR/radiobar-art.jpg`), `RADIOBAR_NO_NOTIFY=1` suppresses notifications.
- iTunes URL exactly: `https://itunes.apple.com/search?term=<quoted>&entity=song&limit=1`; art URL = `artworkUrl100` with `100x100` → `600x600`; year = leading 4 digits of `releaseDate`.
- Never raise into the watch loop or delay bar updates: all network on a daemon thread; every thread body and filesystem publish wrapped.
- Failed lookups are cached as misses (no retries).
- Work on branch `waybar-port`; commit per task with the exact message given; never touch `main`.
- Test counts in steps are approximate — trust test content, not counts. Suite currently: 49 passing.

---

### Task 1: iTunes fetcher + on-disk cache

**Files:**
- Modify: `linux/radiobar` (add `import hashlib`, `import urllib.parse`, `import urllib.request` to imports; new functions after `load_stations`/`find_station` block)
- Test: `linux/test_radiobar.py` (append)

**Interfaces:**
- Produces: `cache_dir() -> Path`; `art_path() -> Path`; `parse_itunes_response(data: bytes) -> dict` with keys `art_url: str|None`, `year: int|None`; `itunes_lookup(title, urlopen=urllib.request.urlopen) -> dict` (same shape, never raises); `art_cache_paths(title) -> (jpg: Path, meta: Path)`; `cached_track_info(title) -> dict|None` (`{"year", "found", "jpg"}`); `store_track_info(title, *, year, image_data)`; `fetch_track_art(title, urlopen=...) -> dict` (`{"year", "found", "jpg"}`, cache-through).

- [ ] **Step 1: Write the failing tests** (append to `linux/test_radiobar.py`)

```python
class TestParseItunesResponse:
    def test_full_result(self):
        data = json.dumps({"results": [{
            "artworkUrl100": "https://x/img/100x100bb.jpg",
            "releaseDate": "1994-03-01T08:00:00Z"}]}).encode()
        info = rb.parse_itunes_response(data)
        assert info == {"art_url": "https://x/img/600x600bb.jpg", "year": 1994}

    def test_no_results(self):
        assert rb.parse_itunes_response(json.dumps({"results": []}).encode()) \
            == {"art_url": None, "year": None}

    def test_garbage(self):
        assert rb.parse_itunes_response(b"{not json") \
            == {"art_url": None, "year": None}

    def test_missing_artwork_still_yields_year(self):
        data = json.dumps({"results": [{"releaseDate": "2003-01-01"}]}).encode()
        assert rb.parse_itunes_response(data) == {"art_url": None, "year": 2003}


class _FakeHTTP:
    """Callable standing in for urllib.request.urlopen."""
    def __init__(self, responses):
        self.responses = responses  # url-substring -> bytes (or OSError)
        self.calls = []

    def __call__(self, url, timeout=None):
        self.calls.append(url)
        for frag, payload in self.responses.items():
            if frag in url:
                if isinstance(payload, Exception):
                    raise payload
                import io

                class R(io.BytesIO):
                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                return R(payload)
        raise OSError("no fake for " + url)


class TestItunesLookup:
    def test_builds_query_url(self):
        fake = _FakeHTTP({"itunes.apple.com": json.dumps({"results": []}).encode()})
        rb.itunes_lookup("Air - Ce Matin-Là", urlopen=fake)
        assert fake.calls[0].startswith(
            "https://itunes.apple.com/search?term=Air%20-%20Ce%20Matin-L")
        assert fake.calls[0].endswith("&entity=song&limit=1")

    def test_network_error_returns_empty(self):
        fake = _FakeHTTP({"itunes.apple.com": OSError("down")})
        assert rb.itunes_lookup("x", urlopen=fake) == {"art_url": None, "year": None}


class TestArtCache:
    def test_fetch_stores_and_second_call_skips_network(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        api = json.dumps({"results": [{
            "artworkUrl100": "https://img.example/100x100bb.jpg",
            "releaseDate": "1990-06-01"}]}).encode()
        fake = _FakeHTTP({"itunes.apple.com": api, "img.example": b"JPEGDATA"})
        info = rb.fetch_track_art("A - B", urlopen=fake)
        assert info["found"] and info["year"] == 1990
        assert Path(info["jpg"]).read_bytes() == b"JPEGDATA"

        fake2 = _FakeHTTP({})  # any network use would raise
        again = rb.fetch_track_art("A - B", urlopen=fake2)
        assert again["found"] and again["year"] == 1990 and fake2.calls == []

    def test_miss_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        fake = _FakeHTTP({"itunes.apple.com": json.dumps({"results": []}).encode()})
        info = rb.fetch_track_art("Obscure - Track", urlopen=fake)
        assert info == {"year": None, "found": False, "jpg": None}
        fake2 = _FakeHTTP({})
        again = rb.fetch_track_art("Obscure - Track", urlopen=fake2)
        assert again["found"] is False and fake2.calls == []
```

Also add `from pathlib import Path` to the test file imports if not present.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd /home/eben/RadioBar && python -m pytest linux/test_radiobar.py -v`
Expected: existing 49 pass; new tests FAIL with `AttributeError: ... no attribute 'parse_itunes_response'`.

- [ ] **Step 3: Implement** (add to `linux/radiobar`; extend imports with `hashlib`, `urllib.parse`, `urllib.request`)

```python
def cache_dir() -> Path:
    override = os.environ.get("RADIOBAR_CACHE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(base) / "radiobar"


def art_path() -> Path:
    override = os.environ.get("RADIOBAR_ART_PATH")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return Path(runtime) / "radiobar-art.jpg"


def parse_itunes_response(data: bytes) -> dict:
    """iTunes Search API payload -> {"art_url", "year"} (both may be None)."""
    empty = {"art_url": None, "year": None}
    try:
        first = json.loads(data)["results"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return empty
    year = None
    release = first.get("releaseDate")
    if isinstance(release, str) and release[:4].isdigit():
        year = int(release[:4])
    art = first.get("artworkUrl100")
    art_url = art.replace("100x100", "600x600") if isinstance(art, str) else None
    return {"art_url": art_url, "year": year}


def itunes_lookup(title: str, urlopen=urllib.request.urlopen) -> dict:
    url = ("https://itunes.apple.com/search?term="
           + urllib.parse.quote(title) + "&entity=song&limit=1")
    try:
        with urlopen(url, timeout=10) as resp:
            return parse_itunes_response(resp.read())
    except OSError:
        return {"art_url": None, "year": None}


def art_cache_paths(title: str):
    key = hashlib.sha1(title.encode()).hexdigest()
    return cache_dir() / f"{key}.jpg", cache_dir() / f"{key}.json"


def cached_track_info(title: str):
    jpg, meta = art_cache_paths(title)
    try:
        info = json.loads(meta.read_text())
    except (OSError, ValueError):
        return None
    found = bool(info.get("found")) and jpg.exists()
    return {"year": info.get("year"), "found": found,
            "jpg": str(jpg) if found else None}


def store_track_info(title: str, *, year, image_data):
    jpg, meta = art_cache_paths(title)
    try:
        meta.parent.mkdir(parents=True, exist_ok=True)
        if image_data:
            jpg.write_bytes(image_data)
        meta.write_text(json.dumps({"year": year, "found": bool(image_data)}))
    except OSError:
        pass


def fetch_track_art(title: str, urlopen=urllib.request.urlopen) -> dict:
    """Cache-through art lookup; failed lookups are cached as misses."""
    cached = cached_track_info(title)
    if cached is not None:
        return cached
    info = itunes_lookup(title, urlopen)
    image_data = None
    if info["art_url"]:
        try:
            with urlopen(info["art_url"], timeout=10) as resp:
                image_data = resp.read()
        except OSError:
            image_data = None
    store_track_info(title, year=info["year"], image_data=image_data)
    jpg, _ = art_cache_paths(title)
    return {"year": info["year"], "found": bool(image_data),
            "jpg": str(jpg) if image_data else None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all pass (~57).

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): iTunes artwork fetcher with on-disk cache"
```

---

### Task 2: ArtworkWorker + publish/notify + watch-loop wiring

**Files:**
- Modify: `linux/radiobar` (add `import threading`; new code after the fetcher block; small changes to `watch`, `cmd_status`, `cmd_stop`)
- Test: `linux/test_radiobar.py` (append)

**Interfaces:**
- Consumes: `fetch_track_art`, `art_path` (Task 1); `pick_title`, `StatusTracker`, `watch`, `cmd_status`, `cmd_stop` (existing).
- Produces: `publish_art(jpg_path: str|None, run=subprocess.run)`; `notify_track(title, station, year, art_jpg, run=subprocess.run)`; `class ArtworkWorker(fetch_fn=..., publish_fn=..., notify_fn=..., spawn=None)` with `track_changed(title, station)` and `clear()`; `watch(sock, worker=None)` (new optional param, default None keeps old behavior).

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestPublishArt:
    def test_copies_and_signals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        src = tmp_path / "cover.jpg"
        src.write_bytes(b"IMG")
        calls = []
        rb.publish_art(str(src), run=lambda cmd, **k: calls.append(cmd))
        assert (tmp_path / "art.png").read_bytes() == b"IMG"
        assert calls == [["pkill", "-RTMIN+6", "waybar"]]

    def test_none_clears_and_signals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        (tmp_path / "art.png").write_bytes(b"OLD")
        calls = []
        rb.publish_art(None, run=lambda cmd, **k: calls.append(cmd))
        assert not (tmp_path / "art.png").exists()
        assert calls == [["pkill", "-RTMIN+6", "waybar"]]


class TestNotifyTrack:
    def test_notifies_with_art_and_year(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        monkeypatch.delenv("RADIOBAR_NO_NOTIFY", raising=False)
        calls = []
        rb.notify_track("A - B", "FIP", 1994, "/tmp/c.jpg",
                        run=lambda cmd, **k: calls.append(cmd))
        assert calls == [["notify-send", "-a", "RadioBar", "-i", "/tmp/c.jpg",
                          "A - B", "FIP · 1994"]]

    def test_no_year_no_art(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        monkeypatch.delenv("RADIOBAR_NO_NOTIFY", raising=False)
        calls = []
        rb.notify_track("A - B", "FIP", None, None,
                        run=lambda cmd, **k: calls.append(cmd))
        assert calls == [["notify-send", "-a", "RadioBar", "A - B", "FIP"]]

    def test_marker_suppresses_duplicate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        monkeypatch.delenv("RADIOBAR_NO_NOTIFY", raising=False)
        calls = []
        run = lambda cmd, **k: calls.append(cmd)
        rb.notify_track("A - B", "FIP", None, None, run=run)
        rb.notify_track("A - B", "FIP", None, None, run=run)
        assert len(calls) == 1
        rb.notify_track("C - D", "FIP", None, None, run=run)
        assert len(calls) == 2

    def test_env_suppresses(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        monkeypatch.setenv("RADIOBAR_NO_NOTIFY", "1")
        calls = []
        rb.notify_track("A - B", "FIP", 2000, None,
                        run=lambda cmd, **k: calls.append(cmd))
        assert calls == []


class TestArtworkWorker:
    def _worker(self, fetched, jobs=None):
        events = {"published": [], "notified": []}
        w = rb.ArtworkWorker(
            fetch_fn=lambda t: fetched,
            publish_fn=lambda jpg: events["published"].append(jpg),
            notify_fn=lambda *a: events["notified"].append(a),
            spawn=(jobs.append if jobs is not None else (lambda fn: fn())))
        return w, events

    def test_fetches_publishes_notifies(self):
        w, ev = self._worker({"year": 1990, "found": True, "jpg": "/c.jpg"})
        w.track_changed("A - B", "FIP")
        assert ev["published"] == ["/c.jpg"]
        assert ev["notified"] == [("A - B", "FIP", 1990, "/c.jpg")]

    def test_station_name_title_clears_art(self):
        w, ev = self._worker({"year": None, "found": False, "jpg": None})
        w.track_changed("BBC Radio 6 Music", "BBC Radio 6 Music")
        assert ev["published"] == [None] and ev["notified"] == []

    def test_dedupes_in_flight(self):
        jobs = []
        w, ev = self._worker({"year": None, "found": False, "jpg": None}, jobs=jobs)
        w.track_changed("A - B", "FIP")
        w.track_changed("A - B", "FIP")
        assert len(jobs) == 1
        jobs[0]()  # completing the job releases the dedupe slot
        w.track_changed("A - B", "FIP")
        assert len(jobs) == 2

    def test_fetch_exception_swallowed_and_slot_released(self):
        jobs = []
        w = rb.ArtworkWorker(fetch_fn=lambda t: (_ for _ in ()).throw(RuntimeError()),
                             publish_fn=lambda jpg: None,
                             notify_fn=lambda *a: None,
                             spawn=jobs.append)
        w.track_changed("A - B", "FIP")
        jobs[0]()  # must not raise
        assert "A - B" not in w.in_flight

    def test_clear_publishes_none(self):
        w, ev = self._worker({"year": None, "found": False, "jpg": None})
        w.clear()
        assert ev["published"] == [None]


class TestWatchArtworkHook:
    def test_title_transition_calls_worker(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        rb.write_last("FIP")
        seen = []

        class W:
            def track_changed(self, title, station):
                seen.append((title, station))

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for _ in rb.OBSERVED_PROPS:
                    self.rfile.readline()
                for title in ("A - B", "A - B", "C - D"):
                    ev = {"event": "property-change",
                          "name": "metadata/by-key/icy-title", "data": title}
                    self.wfile.write(json.dumps(ev).encode() + b"\n")

        sock_path = tmp_path / "radiobar.sock"
        server = socketserver.UnixStreamServer(str(sock_path), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        import socket as socket_mod
        client = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        client.connect(str(sock_path))
        try:
            import pytest
            with pytest.raises(OSError):
                rb.watch(client, worker=W())
        finally:
            client.close()
            thread.join(timeout=5)
            server.server_close()
        # transition fired once per distinct title, not per event
        assert seen == [("A - B", "FIP"), ("C - D", "FIP")]
```

Add `import threading` to the test file imports if not already there (it is, from Task 4 of the port).

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: new tests FAIL with `AttributeError` on `publish_art` / `ArtworkWorker`; `TestWatchArtworkHook` fails with `TypeError: watch() got an unexpected keyword argument 'worker'`.

- [ ] **Step 3: Implement** (add to `linux/radiobar` after the fetcher block; add `import threading`)

```python
def publish_art(jpg_path, run=subprocess.run):
    """Copy cover art to the waybar image module's path (None clears it)."""
    dest = art_path()
    try:
        if jpg_path:
            dest.write_bytes(Path(jpg_path).read_bytes())
        else:
            dest.unlink(missing_ok=True)
    except OSError:
        return
    run(["pkill", "-RTMIN+6", "waybar"], capture_output=True)


def notify_track(title, station, year, art_jpg, run=subprocess.run):
    if os.environ.get("RADIOBAR_NO_NOTIFY") == "1":
        return
    marker = art_path().with_name("radiobar-last-notify")
    try:
        if marker.read_text() == title:
            return
    except OSError:
        pass
    body = station if year is None else f"{station} · {year}"
    cmd = ["notify-send", "-a", "RadioBar"]
    if art_jpg:
        cmd += ["-i", art_jpg]
    cmd += [title, body]
    run(cmd, capture_output=True)
    try:
        marker.write_text(title)
    except OSError:
        pass


class ArtworkWorker:
    """Fetches art off-thread on track changes; publishes to bar + notifies."""

    def __init__(self, fetch_fn=fetch_track_art, publish_fn=publish_art,
                 notify_fn=notify_track, spawn=None):
        self.in_flight = set()
        self.fetch = fetch_fn
        self.publish = publish_fn
        self.notify = notify_fn
        self.spawn = spawn or (lambda fn: threading.Thread(
            target=fn, daemon=True).start())

    def track_changed(self, title, station):
        if not title or title == station:
            self.publish(None)
            return
        if title in self.in_flight:
            return
        self.in_flight.add(title)

        def job():
            try:
                info = self.fetch(title)
                self.publish(info.get("jpg"))
                self.notify(title, station, info.get("year"), info.get("jpg"))
            except Exception:
                pass
            finally:
                self.in_flight.discard(title)

        self.spawn(job)

    def clear(self):
        self.publish(None)
```

Change `watch` to accept and drive the worker (only the marked lines are new):

```python
def watch(sock, worker=None):
    """Observe mpv properties on an open socket; emit bar updates until it closes."""
    tracker = StatusTracker(read_last() or "")
    for i, prop in enumerate(OBSERVED_PROPS, start=1):
        sock.sendall(json.dumps({"command": ["observe_property", i, prop]})
                     .encode() + b"\n")
    emit(tracker.output())
    last_track = None                                        # NEW
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
                if worker is not None:                       # NEW
                    current = pick_title(tracker.icy, tracker.media,
                                         tracker.station)   # NEW
                    if current != last_track:                # NEW
                        last_track = current                 # NEW
                        worker.track_changed(current, tracker.station)  # NEW
```

In `cmd_status`, create one worker for the process and clear art when mpv goes away (only marked lines change):

```python
def cmd_status() -> int:
    worker = ArtworkWorker()                                 # NEW
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
            watch(s, worker=worker)                          # CHANGED
        except OSError:
            pass
        finally:
            s.close()
        worker.clear()                                       # NEW
        emit(waybar_output(running=False))
        time.sleep(2)
```

In `cmd_stop`, clear the bar art too:

```python
def cmd_stop() -> int:
    ipc_command(["quit"])
    publish_art(None)                                        # NEW
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all pass (~68). Note `TestWatch` (existing) passes `worker=None` implicitly — unchanged behavior.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): artwork worker wired into status loop with bar publish and notifications"
```

---

### Task 3: Waybar image module config, docs, live install, push

**Files:**
- Modify: `linux/waybar-snippet.jsonc`, `linux/README.md`
- Modify (live, with backups): `~/.config/waybar/config.jsonc`
- Outside repo: `~/.local/bin/radiobar` (reinstall)

- [ ] **Step 1: Extend `linux/waybar-snippet.jsonc`** — append after the `custom/radio` block:

```jsonc
// Optional: album-art thumbnail. Add "image#radioart" to the same modules
// array, right before "custom/radio":
"image#radioart": {
  "path": "/run/user/1000/radiobar-art.jpg",
  "size": 24,
  "signal": 6,
  "tooltip": false
}
// (Adjust /run/user/1000 if your UID differs — echo $XDG_RUNTIME_DIR.)
```

- [ ] **Step 2: Update `linux/README.md`** — in Features/How-it-works: artwork thumbnail (waybar `image` module) + track-change notification with cover and release year via iTunes Search API lookup, cached in `~/.cache/radiobar/`; note `RADIOBAR_NO_NOTIFY=1` to disable notifications and that notifications need a notification daemon (mako on omarchy). Add the image module block to the install steps.

- [ ] **Step 3: Live install** — backup `~/.config/waybar/config.jsonc` (`cp FILE FILE.bak.$(date +%s)`), add `"image#radioart"` to the modules array immediately before `"custom/radio"` and the module block among definitions (use the real `$XDG_RUNTIME_DIR` for the path), `cp linux/radiobar ~/.local/bin/radiobar`, then `omarchy restart waybar`. Expected: waybar restarts clean; no image shown while stopped (file absent).

- [ ] **Step 4: End-to-end verify** — `radiobar play "SomaFM: Groove Salad"`, wait ~10s, then check: `$XDG_RUNTIME_DIR/radiobar-art.jpg` exists (a real ICY track should resolve on iTunes; if the current track genuinely finds no art, `~/.cache/radiobar/` must contain a miss-marker `.json` instead — either outcome verifies the pipeline); a mako notification fired (check `makoctl history | head` for the track title); `radiobar stop` removes the art file. Run the full suite once more: `python -m pytest linux/test_radiobar.py -q` — all pass. Leave the radio stopped.

- [ ] **Step 5: Commit and push**

```bash
git add linux/waybar-snippet.jsonc linux/README.md
git commit -m "docs(linux): artwork image-module snippet and README updates"
git push origin waybar-port
```

(Pushing updates the existing PR #5.)

---

## Self-Review Notes

- **Spec coverage:** fetcher/cache/miss-caching → Task 1; worker/threading/publish/notify/marker/env-suppress/watch-hook/stop-clear → Task 2; image module snippet, README, live install + verification, PR update → Task 3. Non-goals (tooltip art, MPRIS) have no tasks.
- **Type consistency:** `fetch_track_art` and `cached_track_info` return the same `{"year", "found", "jpg"}` shape consumed by `ArtworkWorker.job`; `watch(sock, worker=None)` default keeps every existing call site valid; `publish_art(None)` is the single "clear" primitive used by worker.clear, cmd_stop, and the station-name path.
- **Placeholder scan:** all steps carry complete code or exact commands; Task 3's config edit describes exact placement and backup procedure.
