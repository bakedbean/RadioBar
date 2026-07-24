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
