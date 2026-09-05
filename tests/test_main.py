from pathlib import Path

import pytest
import requests

import main as main_module
from crawler.downloader import DownloadError


GPX_BYTES = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><trkseg>
  <trkpt lat="46.80" lon="8.60"></trkpt>
  <trkpt lat="46.81" lon="8.60"></trkpt>
 </trkseg></trk>
</gpx>
"""

HTML = """
<html><body>
  <h1 class="title">Sunnig Wichel via Nordgrat</h1>
  <table class="fiche_rando">
    <tr><td class="fiche_rando_b">Tour Datum:</td><td class="fiche_rando">12 Juli 2026</td></tr>
    <tr><td class="fiche_rando_b">Hochtouren Schwierigkeit:</td><td class="fiche_rando">ZS</td></tr>
  </table>
  <a href="https://f.hikr.org/files/gps71129.gpx">gpx</a>
</body></html>
"""

HTML_WITHOUT_GPX = HTML.replace('<a href="https://f.hikr.org/files/gps71129.gpx">gpx</a>', "")


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.content = payload
        self.status_code = 200

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")


@pytest.fixture
def no_delay(monkeypatch):
    """Der Test soll nicht wirklich zwischen den Touren warten."""
    monkeypatch.setattr(main_module.time, "sleep", lambda seconds: None)


@pytest.fixture
def fake_network(monkeypatch, no_delay):
    """Bildet Hikr nach: HTML je Tour, GPX fuer jede .gpx URL."""
    pages: dict[str, str] = {}

    def _get(url, headers=None, timeout=None):
        if url.lower().endswith(".gpx"):
            return FakeResponse(GPX_BYTES)
        if url in pages:
            return FakeResponse(pages[url].encode("utf-8"))
        raise requests.ConnectionError(f"unbekannte URL {url}")

    monkeypatch.setattr("crawler.downloader.requests.get", _get)
    return pages


def test_run_tours_collects_metadata_and_distance(tmp_path: Path, fake_network) -> None:
    url = "https://www.hikr.org/tour/post111.html"
    fake_network[url] = HTML

    results, failures = run(tmp_path, [url])

    assert failures == []
    assert len(results) == 1
    metadata = results[0]
    assert metadata["title"] == "Sunnig Wichel via Nordgrat"
    assert metadata["source_url"] == url
    assert metadata["distance"] == pytest.approx(1.11, abs=0.01)
    assert Path(metadata["gpx_path"]).name == "2026-07-12-sunnig-wichel-via-nordgrat.gpx"


def test_run_tours_handles_tour_without_gpx(tmp_path: Path, fake_network) -> None:
    url = "https://www.hikr.org/tour/post222.html"
    fake_network[url] = HTML_WITHOUT_GPX

    results, failures = run(tmp_path, [url])

    assert failures == []
    assert results[0]["gpx_path"] is None
    assert results[0]["distance"] is None


def test_one_broken_tour_does_not_stop_the_run(tmp_path: Path, fake_network) -> None:
    """Der eigentliche Zweck der Schleife: ein Ausfall darf nicht alles kippen."""
    good_one = "https://www.hikr.org/tour/post111.html"
    good_two = "https://www.hikr.org/tour/post333.html"
    broken = "https://www.hikr.org/tour/post999.html"  # bewusst nicht in pages
    fake_network[good_one] = HTML
    fake_network[good_two] = HTML_WITHOUT_GPX

    results, failures = run(tmp_path, [good_one, broken, good_two])

    assert len(results) == 2
    assert len(failures) == 1
    assert failures[0][0] == broken
    assert isinstance(failures[0][1], DownloadError)


def test_existing_html_is_reused(tmp_path: Path, fake_network, monkeypatch) -> None:
    """Ein zweiter Lauf soll die Seite nicht erneut herunterladen."""
    url = "https://www.hikr.org/tour/post111.html"
    fake_network[url] = HTML
    run(tmp_path, [url])

    calls: list[str] = []
    original = main_module.Downloader.download_url

    def _spy(self, page_url, save_path, encoding="utf-8"):
        calls.append(page_url)
        return original(self, page_url, save_path, encoding)

    monkeypatch.setattr(main_module.Downloader, "download_url", _spy)
    results, failures = run(tmp_path, [url])

    assert calls == []  # HTML kam aus data/html, nicht aus dem Netz
    assert failures == []
    assert results[0]["title"] == "Sunnig Wichel via Nordgrat"


def test_print_summary_survives_missing_values(capsys) -> None:
    """Eine Tour ohne Datum und ohne Distanz darf die Ausgabe nicht sprengen."""
    metadata = {
        "title": None,
        "date_iso": None,
        "distance": None,
        "difficulty_alpine": None,
        "difficulty_hiking": None,
        "difficulty_climbing": None,
        "gpx_path": None,
    }

    main_module.print_summary([metadata], [("https://example.org", DownloadError("kaputt"))])

    output = capsys.readouterr().out
    assert "1 Touren gelesen, 0 mit GPX Datei, 1 fehlgeschlagen" in output
    assert "fehlgeschlagen: https://example.org" in output


def run(tmp_path: Path, urls: list[str]):
    """Kleiner Helfer, damit die Tests nicht in data/ schreiben."""
    return main_module.run_tours(
        urls,
        html_dir=tmp_path / "html",
        gpx_dir=tmp_path / "gpx",
        delay=0,
    )
