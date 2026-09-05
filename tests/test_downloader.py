from pathlib import Path

import pytest
import requests

from crawler.downloader import DownloadError, Downloader, slugify


GPX_URL = "https://f.hikr.org/files/gps71129.gpx"

GPX_BYTES = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<gpx version="1.1" creator="hikr.org">\n'
    b"  <trk><name>Sunnig Wichel</name></trk>\n"
    b"</gpx>\n"
)

HTML_BYTES = b"<!DOCTYPE html><html><body>Seite nicht gefunden</body></html>"


class FakeResponse:
    """Minimaler Ersatz fuer requests.Response, damit die Tests offline laufen."""

    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


def fake_get(content: bytes = GPX_BYTES, status_code: int = 200):
    """Baut einen Ersatz fuer requests.get mit fester Antwort."""

    def _get(url, headers=None, timeout=None):
        return FakeResponse(content, status_code)

    return _get


def test_slugify_writes_out_umlauts_and_drops_special_characters() -> None:
    assert slugify("Piz Palü / Bellavista Überschreitung") == (
        "piz-palue-bellavista-ueberschreitung"
    )
    assert slugify("Grosse Fiescherhorn: Südwestgrat") == "grosse-fiescherhorn-suedwestgrat"
    assert slugify("   ") == ""


def test_download_gpx_builds_name_from_date_and_title(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get())

    path = Downloader().download_gpx(
        GPX_URL,
        title="Sunnig Wichel via Nordgrat",
        date_iso="2026-07-12",
        save_dir=tmp_path,
    )

    assert path.name == "2026-07-12-sunnig-wichel-via-nordgrat.gpx"
    assert path.parent == tmp_path
    assert path.read_bytes() == GPX_BYTES


def test_download_gpx_creates_missing_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get())
    target = tmp_path / "data" / "gpx"

    path = Downloader().download_gpx(GPX_URL, title="Titel", save_dir=target)

    assert target.is_dir()
    assert path.parent == target


def test_download_gpx_without_date_uses_title_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get())

    path = Downloader().download_gpx(
        GPX_URL, title="Sunnig Wichel via Nordgrat", save_dir=tmp_path
    )

    assert path.name == "sunnig-wichel-via-nordgrat.gpx"


def test_download_gpx_without_metadata_falls_back_to_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get())

    path = Downloader().download_gpx(GPX_URL, save_dir=tmp_path)

    assert path.name == "gps71129.gpx"


def test_download_gpx_url_fallback_ignores_query_string(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get())

    path = Downloader().download_gpx(f"{GPX_URL}?token=abc123", save_dir=tmp_path)

    assert path.name == "gps71129.gpx"


def test_download_gpx_truncates_long_titles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get())
    long_title = "Sehr lange Tourbeschreibung mit vielen Woertern " * 5

    path = Downloader().download_gpx(
        GPX_URL, title=long_title, date_iso="2026-07-12", save_dir=tmp_path
    )

    title_part = path.stem[len("2026-07-12-"):]
    assert len(title_part) <= 80
    assert not title_part.endswith("-")


def test_download_gpx_overwrites_existing_file(tmp_path: Path, monkeypatch) -> None:
    """Ein zweiter Lauf ueber dieselbe Tour soll denselben Stand erzeugen."""
    monkeypatch.setattr(requests, "get", fake_get())
    arguments = dict(title="Sunnig Wichel", date_iso="2026-07-12", save_dir=tmp_path)

    first = Downloader().download_gpx(GPX_URL, **arguments)
    second = Downloader().download_gpx(GPX_URL, **arguments)

    assert first == second
    assert len(list(tmp_path.iterdir())) == 1


def test_download_gpx_raises_on_http_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get(b"", status_code=404))

    with pytest.raises(DownloadError, match="404"):
        Downloader().download_gpx(GPX_URL, title="Titel", save_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_gpx_raises_on_network_error(tmp_path: Path, monkeypatch) -> None:
    def _raise(url, headers=None, timeout=None):
        raise requests.ConnectionError("keine Verbindung")

    monkeypatch.setattr(requests, "get", _raise)

    with pytest.raises(DownloadError, match="Network error"):
        Downloader().download_gpx(GPX_URL, title="Titel", save_dir=tmp_path)


def test_download_gpx_raises_when_response_is_html(tmp_path: Path, monkeypatch) -> None:
    """Hikr liefert bei toten Links eine HTML Seite mit Status 200."""
    monkeypatch.setattr(requests, "get", fake_get(HTML_BYTES))

    with pytest.raises(DownloadError, match="not a GPX file"):
        Downloader().download_gpx(GPX_URL, title="Titel", save_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_gpx_raises_when_no_name_can_be_derived(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", fake_get())

    with pytest.raises(DownloadError, match="Cannot derive"):
        Downloader().download_gpx("https://www.hikr.org/tour/post202345.html", save_dir=tmp_path)
