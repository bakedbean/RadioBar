"""Tests for the radiobar script (loaded from the extensionless file)."""
import importlib.machinery
import importlib.util
import json
import pathlib
import socketserver
import sys
import threading
import time
from pathlib import Path


def _load():
    path = pathlib.Path(__file__).parent / "radiobar"
    loader = importlib.machinery.SourceFileLoader("radiobar", str(path))
    spec = importlib.util.spec_from_loader("radiobar", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["radiobar"] = mod
    loader.exec_module(mod)
    return mod


rb = _load()


def _mpris_active(playing=True, artist="Ar", title="Ti", player="spotify"):
    return {"source": "mpris", "player": player, "playing": playing,
            "artist": artist, "title": title, "art_url": None,
            "station": None}


def _radio_active(playing=True, title="A - B", station="FIP"):
    return {"source": "radio", "player": None, "playing": playing,
            "artist": None, "title": title, "art_url": None,
            "station": station}


class TestScrollWindow:
    def test_wraps_with_pad(self):
        text = "0123456789"  # len 10, window 6
        assert rb.scroll_window(text, 6, 0) == "012345"
        # offset 8: chars 8,9 then the pad begins
        assert rb.scroll_window(text, 6, 8) == "89" + rb.SCROLL_PAD[:4]
        # offset wraps modulo len(text) + len(pad) = 17
        assert rb.scroll_window(text, 6, 17) == rb.scroll_window(text, 6, 0)


class TestPlayerIcon:
    def test_known_players(self):
        assert rb.player_icon("spotify") == rb.PLAYER_ICONS["spotify"]
        assert rb.player_icon("de.haeckerfelix.shortwave") == \
            rb.PLAYER_ICONS["de.haeckerfelix.shortwave"]

    def test_substring_match_and_fallback(self):
        assert rb.player_icon("spotify.instance42") == rb.PLAYER_ICONS["spotify"]
        assert rb.player_icon("firefox") == rb.ICON_MPRIS_DEFAULT
        assert rb.player_icon(None) == rb.ICON_MPRIS_DEFAULT


class TestRenderer:
    def _renderer(self):
        return rb.Renderer(choose=lambda colors: colors[0])

    def test_idle(self):
        out = self._renderer().render(dict(rb.IDLE_ACTIVE))
        assert out["class"] == "idle" and out["text"] == rb.ICON_IDLE

    def test_mpris_playing_has_icons_colors_and_tooltip(self):
        out = self._renderer().render(_mpris_active())
        assert out["class"] == "playing" and out["markup"] == "pango"
        assert rb.PLAYER_ICONS["spotify"] in out["text"]
        assert rb.COLORS[0] in out["text"]
        assert "Ar - Ti" in out["text"]
        assert out["tooltip"] == "Ar - Ti\nSpotify"

    def test_mpris_paused_appends_status_icon(self):
        out = self._renderer().render(_mpris_active(playing=False))
        assert out["class"] == "paused"
        assert rb.ICON_MPRIS_PAUSED in out["text"]

    def test_radio_uses_play_pause_icon_only(self):
        r = self._renderer()
        out = r.render(_radio_active(playing=True))
        assert rb.ICON_PLAY in out["text"] and out["class"] == "playing"
        assert rb.ICON_MPRIS_PAUSED not in out["text"]
        out = r.render(_radio_active(playing=False))
        assert rb.ICON_PAUSE in out["text"] and out["class"] == "paused"
        assert out["tooltip"] == "A - B\nFIP"

    def test_short_title_no_tick_needed(self):
        r = self._renderer()
        r.render(_mpris_active())
        assert r.needs_tick() is False

    def test_long_title_scrolls_after_pause(self):
        r = self._renderer()
        long = _mpris_active(artist=None, title="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef")
        r.render(long)
        assert r.needs_tick() is True
        # first PAUSE_TICKS renders hold the window at offset 0
        first = r.render(long)["text"]
        for _ in range(rb.PAUSE_TICKS - 1):
            held = r.render(long)["text"]
        assert held == first
        moved = r.render(long)["text"]
        assert moved != first

    def test_track_change_resets_scroll_and_recolors(self):
        picks = iter(rb.COLORS)
        r = rb.Renderer(choose=lambda colors: next(picks))
        a = r.render(_mpris_active(title="x" * 40))
        b = r.render(_mpris_active(title="y" * 40))  # new track
        # colors advanced: 2 picks per track with our fake chooser
        assert rb.COLORS[0] in a["text"] and rb.COLORS[2] in b["text"]

    def test_pango_special_chars_escaped(self):
        out = self._renderer().render(
            _mpris_active(artist="Simon & Garfunkel", title="<Sound>"))
        assert "&amp;" in out["text"] and "&lt;Sound&gt;" in out["text"]
        assert "Simon & Garfunkel" in out["tooltip"]  # tooltip unescaped


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

    def test_unwritable_config_dir_falls_back_to_builtins(
            self, tmp_path, monkeypatch):
        readonly_parent = tmp_path / "readonly"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o555)
        try:
            monkeypatch.setenv("RADIOBAR_CONFIG_DIR",
                                str(readonly_parent / "radiobar"))
            assert rb.load_stations() == rb.BUILTIN_STATIONS
        finally:
            readonly_parent.chmod(0o755)


class TestFindStation:
    def test_exact_name(self):
        s = rb.find_station(rb.BUILTIN_STATIONS, "FIP")
        assert s is not None and s["streamURL"].endswith("fip-midfi.mp3")

    def test_case_insensitive(self):
        assert rb.find_station(rb.BUILTIN_STATIONS, "fip") is not None

    def test_unknown_returns_none(self):
        assert rb.find_station(rb.BUILTIN_STATIONS, "Nope FM") is None


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


class _PartialLineMpvHandler(socketserver.StreamRequestHandler):
    """Simulates mpv dribbling an unsolicited event plus a split response
    line across multiple writes, to exercise buffered/partial-line parsing."""

    def handle(self):
        line = self.rfile.readline()
        req = json.loads(line)
        self.server.received.append(req)
        resp = {"request_id": req.get("request_id", 0), "error": "success",
                "data": None}
        event = json.dumps({"event": "playback-restart"}) + "\n"
        resp_json = json.dumps(resp) + "\n"
        # Write an unsolicited event, then a PARTIAL fragment of the real
        # response (no trailing newline) in the same write.
        split_at = len(resp_json) // 2
        self.wfile.write(event.encode())
        self.wfile.write(resp_json[:split_at].encode())
        self.wfile.flush()
        time.sleep(0.05)
        # Complete the fragment in a second write.
        self.wfile.write(resp_json[split_at:].encode())


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

    def test_partial_line_across_recvs_still_parses_response(
            self, tmp_path, monkeypatch):
        # Regression: an unsolicited event line followed by a response line
        # split across two writes must not be treated as "mpv unreachable".
        sock_path = tmp_path / "radiobar.sock"
        monkeypatch.setenv("RADIOBAR_SOCK", str(sock_path))
        server = socketserver.UnixStreamServer(str(sock_path),
                                                _PartialLineMpvHandler)
        server.received = []
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        resp = rb.ipc_command(["cycle", "pause"])
        thread.join(timeout=5)
        server.server_close()
        assert resp is not None, "ipc_command incorrectly returned None"
        assert resp["error"] == "success"
        assert server.received[0]["command"] == ["cycle", "pause"]


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


class _FakePopen:
    def __init__(self, argv, **kwargs):
        _FakePopen.calls.append((argv, kwargs))


class TestLaunchMpv:
    def test_spawns_mpv_with_expected_argv(self, tmp_path, monkeypatch):
        sock_path = tmp_path / "radiobar.sock"
        monkeypatch.setenv("RADIOBAR_SOCK", str(sock_path))
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        _FakePopen.calls = []
        monkeypatch.setattr(rb.subprocess, "Popen", _FakePopen)

        station = {"name": "FIP", "streamURL": "https://example.com/s.mp3",
                   "genre": "", "websiteURL": None}
        rb.launch_mpv(station)

        assert len(_FakePopen.calls) == 1
        argv, kwargs = _FakePopen.calls[0]
        assert argv == [
            "mpv", "--no-video", f"--input-ipc-server={sock_path}",
            "--stream-lavf-o=reconnect_streamed=1,reconnect_delay_max=10",
            "https://example.com/s.mp3",
        ]
        assert kwargs["start_new_session"] is True
        assert kwargs["stdout"] is rb.subprocess.DEVNULL
        assert kwargs["stderr"] is rb.subprocess.DEVNULL
        assert rb.read_last() == "FIP"


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

    def test_unknown_choice_notifies_and_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "cmd_play", lambda name: 1)
        monkeypatch.setattr(rb, "find_menu_cmd",
                            lambda which=None: ["walker", "--dmenu"])
        run, calls = self._fake_run("Nope FM\n")
        assert rb.cmd_menu(run=run) == 1
        assert any(c[0][0] == "notify-send" for c in calls)
        notify_call = next(c for c in calls if c[0][0] == "notify-send")
        assert "Nope FM" in notify_call[0][2]


class TestParseItunesResponse:
    def test_full_result(self):
        data = json.dumps({"results": [{
            "artworkUrl100": "https://x/img/100x100bb.jpg",
            "releaseDate": "1994-03-01T08:00:00Z"}]}).encode()
        info = rb.parse_itunes_response(data)
        assert info == {"art_url": "https://x/img/600x600bb.jpg",
                        "art_url_small": "https://x/img/100x100bb.jpg",
                        "year": 1994}

    def test_no_results(self):
        assert rb.parse_itunes_response(json.dumps({"results": []}).encode()) \
            == {"art_url": None, "art_url_small": None, "year": None}

    def test_garbage(self):
        assert rb.parse_itunes_response(b"{not json") \
            == {"art_url": None, "art_url_small": None, "year": None}

    def test_missing_artwork_still_yields_year(self):
        data = json.dumps({"results": [{"releaseDate": "2003-01-01"}]}).encode()
        assert rb.parse_itunes_response(data) == \
            {"art_url": None, "art_url_small": None, "year": 2003}


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
        assert rb.itunes_lookup("x", urlopen=fake) == \
            {"art_url": None, "art_url_small": None, "year": None}

    def test_incomplete_read_returns_empty(self):
        import http.client

        class _RaisingResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                raise http.client.IncompleteRead(b"partial")

        fake = lambda url, timeout=None: _RaisingResp()
        assert rb.itunes_lookup("x", urlopen=fake) == \
            {"art_url": None, "art_url_small": None, "year": None}


class TestArtCache:
    def test_fetch_stores_and_second_call_skips_network(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        api = json.dumps({"results": [{
            "artworkUrl100": "https://img.example/100x100bb.jpg",
            "releaseDate": "1990-06-01"}]}).encode()
        fake = _FakeHTTP({"itunes.apple.com": api,
                          "img.example/600x600bb.jpg": b"BIGDATA",
                          "img.example/100x100bb.jpg": b"SMALLDATA"})
        info = rb.fetch_track_art("A - B", urlopen=fake)
        assert info["found"] and info["year"] == 1990
        assert Path(info["jpg"]).read_bytes() == b"BIGDATA"
        assert Path(info["jpg_small"]).read_bytes() == b"SMALLDATA"

        fake2 = _FakeHTTP({})  # any network use would raise
        again = rb.fetch_track_art("A - B", urlopen=fake2)
        assert again["found"] and again["year"] == 1990 and fake2.calls == []
        assert Path(again["jpg_small"]).read_bytes() == b"SMALLDATA"

    def test_miss_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        fake = _FakeHTTP({"itunes.apple.com": json.dumps({"results": []}).encode()})
        info = rb.fetch_track_art("Obscure - Track", urlopen=fake)
        assert info == {"year": None, "found": False, "jpg": None, "jpg_small": None}
        fake2 = _FakeHTTP({})
        again = rb.fetch_track_art("Obscure - Track", urlopen=fake2)
        assert again["found"] is False and fake2.calls == []

    def test_incomplete_read_on_image_is_treated_as_miss(self, tmp_path, monkeypatch):
        import http.client
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        api = json.dumps({"results": [{
            "artworkUrl100": "https://img.example/100x100bb.jpg",
            "releaseDate": "1990-06-01"}]}).encode()

        class _RaisingImgResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                raise http.client.IncompleteRead(b"partial")

        def fake(url, timeout=None):
            if "itunes.apple.com" in url:
                import io

                class R(io.BytesIO):
                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                return R(api)
            if "img.example" in url:
                return _RaisingImgResp()
            raise OSError("no fake for " + url)

        info = rb.fetch_track_art("A - B", urlopen=fake)
        assert info["found"] is False
        assert info["jpg"] is None
        assert info["jpg_small"] is None

        # the miss is cached: a second call must not touch the network
        fake2 = _FakeHTTP({})
        again = rb.fetch_track_art("A - B", urlopen=fake2)
        assert again["found"] is False and fake2.calls == []

    def test_non_dict_meta_json_is_treated_as_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        _, _, meta = rb.art_cache_paths("Some Title")
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps([1, 2]))
        assert rb.cached_track_info("Some Title") is None


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

    def test_missing_pkill_binary_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))

        def raising_fn(cmd, **k):
            raise FileNotFoundError("pkill not found")

        rb.publish_art(None, run=raising_fn)  # must not raise


class TestNotifyTrack:
    def test_notifies_with_art_and_year(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        monkeypatch.delenv("RADIOBAR_NO_NOTIFY", raising=False)
        calls = []
        rb.notify_track("A - B", "FIP", 1994, "/tmp/c.jpg",
                        run=lambda cmd, **k: calls.append(cmd))
        assert calls == [["notify-send", "-a", "RadioBar", "-i", "/tmp/c.jpg",
                          "--", "A - B", "FIP · 1994"]]

    def test_no_year_no_art(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ART_PATH", str(tmp_path / "art.png"))
        monkeypatch.delenv("RADIOBAR_NO_NOTIFY", raising=False)
        calls = []
        rb.notify_track("A - B", "FIP", None, None,
                        run=lambda cmd, **k: calls.append(cmd))
        assert calls == [["notify-send", "-a", "RadioBar", "--", "A - B", "FIP"]]

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


class TestArtPath:
    def test_default_basename_is_jpg(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RADIOBAR_ART_PATH", raising=False)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        assert rb.art_path().name == "radiobar-art.jpg"


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
        w, ev = self._worker({"year": 1990, "found": True, "jpg": "/c.jpg",
                              "jpg_small": "/c-small.jpg"})
        w.track_changed("A - B", "FIP")
        assert ev["published"] == ["/c-small.jpg"]
        assert ev["notified"] == [("A - B", "FIP", 1990, "/c.jpg")]

    def test_station_name_title_clears_art(self):
        w, ev = self._worker({"year": None, "found": False, "jpg": None,
                              "jpg_small": None})
        w.track_changed("BBC Radio 6 Music", "BBC Radio 6 Music")
        assert ev["published"] == [None] and ev["notified"] == []

    def test_dedupes_in_flight(self):
        jobs = []
        w, ev = self._worker({"year": None, "found": False, "jpg": None,
                              "jpg_small": None}, jobs=jobs)
        w.track_changed("A - B", "FIP")
        w.track_changed("A - B", "FIP")
        assert len(jobs) == 1
        jobs[0]()  # completing the job releases the dedupe slot
        # The deduped second call must not have bumped gen and orphaned the
        # first (still in-flight) job's publish — its completion should
        # still fire normally.
        assert ev["published"] == [None]
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
        w, ev = self._worker({"year": None, "found": False, "jpg": None,
                              "jpg_small": None})
        w.clear()
        assert ev["published"] == [None]

    def test_stale_job_after_newer_track_does_not_publish(self):
        jobs = []
        fetched = {
            "A - B": {"year": 1990, "found": True, "jpg": "/a.jpg",
                      "jpg_small": "/a-small.jpg"},
            "C - D": {"year": 1991, "found": True, "jpg": "/c.jpg",
                      "jpg_small": "/c-small.jpg"},
        }
        events = {"published": [], "notified": []}
        w = rb.ArtworkWorker(
            fetch_fn=lambda t: fetched[t],
            publish_fn=lambda jpg: events["published"].append(jpg),
            notify_fn=lambda *a: events["notified"].append(a),
            spawn=jobs.append)
        w.track_changed("A - B", "FIP")  # gen 1, job A queued
        assert len(jobs) == 1
        w.track_changed("C - D", "FIP")  # gen 2, job B queued
        assert len(jobs) == 2
        jobs[1]()  # B (newer) completes first
        jobs[0]()  # A's stale job completes after
        assert events["published"] == ["/c-small.jpg"]
        assert events["notified"] == [("C - D", "FIP", 1991, "/c.jpg")]
        assert "A - B" not in w.in_flight
        assert "C - D" not in w.in_flight

    def test_stale_job_after_clear_does_not_publish(self):
        jobs = []
        events = {"published": [], "notified": []}
        w = rb.ArtworkWorker(
            fetch_fn=lambda t: {"year": 1990, "found": True, "jpg": "/a.jpg",
                                "jpg_small": "/a-small.jpg"},
            publish_fn=lambda jpg: events["published"].append(jpg),
            notify_fn=lambda *a: events["notified"].append(a),
            spawn=jobs.append)
        w.track_changed("A - B", "FIP")  # gen 1, job queued
        assert len(jobs) == 1
        w.clear()  # gen 2, publishes None
        jobs[0]()  # stale job completes after clear
        assert events["published"] == [None]
        assert events["notified"] == []
        assert "A - B" not in w.in_flight

    def test_a_b_a_replay_publishes_current_track(self):
        # A -> B -> A: the third call (A again) must be deduped (A's
        # original job is still in-flight) but must re-mark A as the
        # *current* title, so when A's original job finally completes it
        # publishes A's art instead of being suppressed as "stale".
        jobs = []
        fetched = {
            "A - B": {"year": 1990, "found": True, "jpg": "/a.jpg",
                      "jpg_small": "/a-small.jpg"},
            "C - D": {"year": 1991, "found": True, "jpg": "/c.jpg",
                      "jpg_small": "/c-small.jpg"},
        }
        events = {"published": [], "notified": []}
        w = rb.ArtworkWorker(
            fetch_fn=lambda t: fetched[t],
            publish_fn=lambda jpg: events["published"].append(jpg),
            notify_fn=lambda *a: events["notified"].append(a),
            spawn=jobs.append)
        w.track_changed("A - B", "FIP")  # job A queued, A in-flight
        w.track_changed("C - D", "FIP")  # job B queued, C-D in-flight
        assert len(jobs) == 2
        w.track_changed("A - B", "FIP")  # A replayed; still in-flight -> deduped
        assert len(jobs) == 2  # no third job spawned
        jobs[0]()  # A's ORIGINAL job runs now; A is current again
        assert events["published"] == ["/a-small.jpg"]
        assert events["notified"] == [("A - B", "FIP", 1990, "/a.jpg")]

    def test_replay_after_clear_publishes_current_track(self):
        # clear() then replaying the same title (still in-flight from
        # before the clear) must not permanently suppress that title's art.
        jobs = []
        events = {"published": [], "notified": []}
        w = rb.ArtworkWorker(
            fetch_fn=lambda t: {"year": 1990, "found": True, "jpg": "/a.jpg",
                                "jpg_small": "/a-small.jpg"},
            publish_fn=lambda jpg: events["published"].append(jpg),
            notify_fn=lambda *a: events["notified"].append(a),
            spawn=jobs.append)
        w.track_changed("A - B", "FIP")  # job queued, A in-flight
        assert len(jobs) == 1
        w.clear()  # publishes None
        w.track_changed("A - B", "FIP")  # A still in-flight -> deduped, re-marked current
        assert len(jobs) == 1  # no second job spawned
        jobs[0]()  # A's original job runs now; A is current again
        assert events["published"] == [None, "/a-small.jpg"]
        assert events["notified"] == [("A - B", "FIP", 1990, "/a.jpg")]


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


class TestWriteLastRobustness:
    def test_unwritable_state_dir_does_not_raise(self, tmp_path, monkeypatch):
        ro = tmp_path / "ro"
        ro.mkdir()
        ro.chmod(0o555)
        try:
            monkeypatch.setenv("RADIOBAR_STATE_DIR", str(ro / "radiobar"))
            rb.write_last("FIP")  # unwritable state dir must not crash toggle/play
            assert rb.read_last() is None
        finally:
            ro.chmod(0o755)


class TestCmdMenuNotifyRobustness:
    def test_missing_notify_send_no_menu_tool_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(rb, "find_menu_cmd", lambda which=None: None)

        def run(cmd, **kwargs):
            raise FileNotFoundError("notify-send")

        assert rb.cmd_menu(run=run) == 1

    def test_missing_notify_send_unknown_choice_does_not_raise(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "find_menu_cmd",
                            lambda which=None: ["walker", "--dmenu"])
        monkeypatch.setattr(rb, "cmd_play", lambda name: 1)

        def run(cmd, **kwargs):
            if cmd[0] == "notify-send":
                raise FileNotFoundError("notify-send")

            class R:
                stdout = "Nope FM\n"
            return R()

        assert rb.cmd_menu(run=run) == 1


class TestParsePlayerctlLine:
    def test_playing_line(self):
        line = "spotify\tPlaying\tAir\tLa Femme d'Argent\thttps://i.scdn.co/image/x\n"
        name, state = rb.parse_playerctl_line(line)
        assert name == "spotify"
        assert state == {"status": "Playing", "artist": "Air",
                         "title": "La Femme d'Argent",
                         "art_url": "https://i.scdn.co/image/x"}

    def test_empty_fields_become_none(self):
        name, state = rb.parse_playerctl_line("firefox\tPaused\t\tSome Video\t\n")
        assert name == "firefox"
        assert state == {"status": "Paused", "artist": None,
                         "title": "Some Video", "art_url": None}

    def test_blank_line_is_ignored(self):
        assert rb.parse_playerctl_line("\n") is None
        assert rb.parse_playerctl_line("   \n") is None

    def test_wrong_field_count_is_ignored(self):
        assert rb.parse_playerctl_line("garbage line\n") is None
        assert rb.parse_playerctl_line("a\tb\tc\n") is None

    def test_stopped_or_cleared_status_drops_player(self):
        assert rb.parse_playerctl_line("spotify\tStopped\t\t\t\n") == ("spotify", None)
        assert rb.parse_playerctl_line("spotify\t\t\t\t\n") == ("spotify", None)

    def test_empty_player_name_is_ignored(self):
        assert rb.parse_playerctl_line("\tPlaying\tA\tT\t\n") is None


def _radio(playing=True, icy="A - B", station="FIP", seq=1):
    return {"running": True, "paused": not playing, "icy": icy,
            "media": None, "station": station, "seq": seq}


def _player(status="Playing", artist="Ar", title="Ti", art_url=None, seq=1):
    return {"status": status, "artist": artist, "title": title,
            "art_url": art_url, "seq": seq}


class TestGuardAction:
    def test_new_playing_player_while_radio_plays_fires(self):
        assert rb.guard_action({}, {"spotify": _player("Playing")}, True) is True

    def test_transition_paused_to_playing_fires(self):
        assert rb.guard_action({"spotify": _player("Paused")},
                               {"spotify": _player("Playing")}, True) is True

    def test_level_state_does_not_fire(self):
        # already Playing in prev — no edge, no fire (can't fight a user
        # who resumes radio while spotify is left playing)
        assert rb.guard_action({"spotify": _player("Playing")},
                               {"spotify": _player("Playing")}, True) is False

    def test_radio_not_playing_never_fires(self):
        assert rb.guard_action({}, {"spotify": _player("Playing")}, False) is False

    def test_mpv_player_never_fires(self):
        # radio's own mpv seen through mpv-mpris must not pause radio
        assert rb.guard_action({}, {"mpv": _player("Playing")}, True) is False

    def test_paused_player_does_not_fire(self):
        assert rb.guard_action({}, {"spotify": _player("Paused")}, True) is False


class TestArbiter:
    def test_idle_when_nothing(self):
        active = rb.arbiter({"running": False}, {})
        assert active["source"] == "idle" and active["playing"] is False

    def test_playing_radio_beats_paused_player(self):
        active = rb.arbiter(_radio(playing=True, seq=1),
                            {"spotify": _player("Paused", seq=9)})
        assert active["source"] == "radio" and active["playing"] is True
        assert active["title"] == "A - B" and active["station"] == "FIP"

    def test_playing_player_beats_paused_radio(self):
        active = rb.arbiter(_radio(playing=False, seq=9),
                            {"spotify": _player("Playing", seq=1)})
        assert active["source"] == "mpris" and active["player"] == "spotify"
        assert active["artist"] == "Ar" and active["title"] == "Ti"

    def test_recency_breaks_playing_tie(self):
        active = rb.arbiter(_radio(playing=True, seq=5),
                            {"spotify": _player("Playing", seq=7)})
        assert active["source"] == "mpris"
        active = rb.arbiter(_radio(playing=True, seq=8),
                            {"spotify": _player("Playing", seq=7)})
        assert active["source"] == "radio"

    def test_mpv_player_ignored_while_radio_runs(self):
        active = rb.arbiter(_radio(playing=True, seq=1),
                            {"mpv": _player("Playing", seq=9)})
        assert active["source"] == "radio"

    def test_mpv_player_shown_when_radio_stopped(self):
        active = rb.arbiter({"running": False},
                            {"mpv": _player("Playing", title="Some Film")})
        assert active["source"] == "mpris" and active["player"] == "mpv"

    def test_titleless_player_ignored(self):
        active = rb.arbiter({"running": False},
                            {"spotify": _player(title=None)})
        assert active["source"] == "idle"

    def test_paused_players_recency(self):
        active = rb.arbiter({"running": False},
                            {"spotify": _player("Paused", seq=2),
                             "firefox": _player("Paused", title="V", seq=5)})
        assert active["player"] == "firefox"

    def test_radio_title_uses_pick_title_fallback(self):
        active = rb.arbiter(_radio(icy=None), {})
        assert active["title"] == "FIP"


class TestStateStore:
    def test_initial_snapshot_is_idle(self):
        store = rb.StateStore()
        radio, players = store.snapshot()
        assert radio == {"running": False} and players == {}

    def test_set_radio_stamps_increasing_seq_and_sets_event(self):
        store = rb.StateStore()
        store.set_radio({"running": True, "paused": False, "icy": None,
                         "media": None, "station": "FIP"})
        assert store.changed.is_set()
        radio1, _ = store.snapshot()
        store.set_radio({"running": True, "paused": True, "icy": None,
                         "media": None, "station": "FIP"})
        radio2, _ = store.snapshot()
        assert radio2["seq"] > radio1["seq"]

    def test_update_and_drop_player(self):
        store = rb.StateStore()
        store.update_player("spotify", {"status": "Playing", "artist": "A",
                                        "title": "T", "art_url": None})
        _, players = store.snapshot()
        assert players["spotify"]["status"] == "Playing"
        assert "seq" in players["spotify"]
        store.update_player("spotify", None)
        _, players = store.snapshot()
        assert players == {}

    def test_player_seq_advances_across_updates(self):
        store = rb.StateStore()
        store.update_player("spotify", {"status": "Paused", "artist": None,
                                        "title": "T", "art_url": None})
        store.update_player("firefox", {"status": "Playing", "artist": None,
                                        "title": "V", "art_url": None})
        _, players = store.snapshot()
        assert players["firefox"]["seq"] > players["spotify"]["seq"]

    def test_snapshot_is_a_copy(self):
        store = rb.StateStore()
        store.update_player("spotify", {"status": "Playing", "artist": None,
                                        "title": "T", "art_url": None})
        _, players = store.snapshot()
        players["spotify"]["status"] = "Paused"
        _, players2 = store.snapshot()
        assert players2["spotify"]["status"] == "Playing"
