"""Tests for the radiobar script (loaded from the extensionless file)."""
import importlib.machinery
import importlib.util
import json
import pathlib
import socketserver
import sys
import threading
import time


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
