from pathlib import Path

import pytest
import requests

from crawler.downloader import (
    CrawlBlockedError,
    DownloadError,
    Downloader,
    TransientDownloadError,
    build_polite_downloader,
)
from crawler.politeness import MIN_DELAY_SECONDS, RateLimiter, RetryPolicy, RobotsPolicy


FIXTURES = Path(__file__).parent / "fixtures" / "hikr"
URL = "https://www.hikr.org/region146/ski/"
ROBOTS_URL = "https://www.hikr.org/robots.txt"
GPX_URL = "https://f.hikr.org/files/gps71129.gpx"
GPX_BYTES = b'<?xml version="1.0"?><gpx version="1.1"><trk></trk></gpx>'


class Response:
    """Minimaler Ersatz fuer requests.Response mit Status, Text und Headern."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        content: bytes | None = None,
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = headers or {}


@pytest.fixture
def scripted(monkeypatch):
    """
    requests.get liefert die vorbereiteten Antworten der Reihe nach. Eine
    Exception in der Liste wird geworfen. calls haelt jede Anfrage fest.
    """
    state = {"queue": [], "calls": []}

    def _get(url, headers=None, timeout=None):
        state["calls"].append(url)
        if not state["queue"]:
            raise AssertionError(f"Unerwartete Anfrage an {url}")
        item = state["queue"].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "get", _get)
    return state


def polite(fake_clock, retry: RetryPolicy | None = RetryPolicy(), robots=None) -> Downloader:
    limiter = RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)
    return Downloader(limiter=limiter, retry=retry, robots=robots)


# --- Abbruch statt Wiederholung -----------------------------------------


def test_403_ends_the_run_without_retry(scripted, fake_clock) -> None:
    scripted["queue"] = [Response(403)]

    with pytest.raises(CrawlBlockedError, match="403"):
        polite(fake_clock).fetch_html(URL)

    assert scripted["calls"] == [URL]


@pytest.mark.parametrize("status", [200, 403])
def test_cloudflare_challenge_ends_the_run(scripted, fake_clock, status: int) -> None:
    scripted["queue"] = [Response(status, headers={"cf-mitigated": "challenge"})]

    with pytest.raises(CrawlBlockedError, match="Cloudflare"):
        polite(fake_clock).fetch_html(URL)


def test_429_with_short_retry_after_is_waited_once(scripted, fake_clock) -> None:
    scripted["queue"] = [Response(429, headers={"Retry-After": "30"}), Response(200, text="ok")]

    assert polite(fake_clock).fetch_html(URL) == "ok"
    assert 30.0 in fake_clock.sleeps
    assert len(scripted["calls"]) == 2


def test_429_twice_ends_the_run(scripted, fake_clock) -> None:
    scripted["queue"] = [
        Response(429, headers={"Retry-After": "30"}),
        Response(429, headers={"Retry-After": "30"}),
    ]

    with pytest.raises(CrawlBlockedError, match="429"):
        polite(fake_clock).fetch_html(URL)

    assert len(scripted["calls"]) == 2


def test_429_without_retry_after_ends_the_run(scripted, fake_clock) -> None:
    scripted["queue"] = [Response(429)]

    with pytest.raises(CrawlBlockedError):
        polite(fake_clock).fetch_html(URL)

    assert len(scripted["calls"]) == 1


def test_429_with_long_retry_after_ends_the_run_without_waiting(scripted, fake_clock) -> None:
    scripted["queue"] = [Response(429, headers={"Retry-After": "900"})]

    with pytest.raises(CrawlBlockedError):
        polite(fake_clock).fetch_html(URL)

    assert 900.0 not in fake_clock.sleeps


# --- Wiederholungen -------------------------------------------------------


def test_503_is_retried_with_growing_waits(scripted, fake_clock) -> None:
    scripted["queue"] = [Response(503), Response(503), Response(200, text="ok")]

    assert polite(fake_clock).fetch_html(URL) == "ok"
    assert 15.0 in fake_clock.sleeps
    assert 60.0 in fake_clock.sleeps
    assert len(scripted["calls"]) == 3


def test_503_three_times_is_a_transient_failure(scripted, fake_clock) -> None:
    scripted["queue"] = [Response(503), Response(503), Response(503)]

    with pytest.raises(TransientDownloadError, match="503"):
        polite(fake_clock).fetch_html(URL)

    assert len(scripted["calls"]) == 3


def test_network_error_is_retried_then_transient(scripted, fake_clock) -> None:
    scripted["queue"] = [requests.ConnectionError("weg")] * 3

    with pytest.raises(TransientDownloadError, match="Network error"):
        polite(fake_clock).fetch_html(URL)

    assert len(scripted["calls"]) == 3


def test_without_retry_policy_a_network_error_fails_at_once(scripted) -> None:
    """Der einfache Downloader bleibt beim alten Verhalten."""
    scripted["queue"] = [requests.ConnectionError("weg")]

    with pytest.raises(DownloadError) as caught:
        Downloader().fetch_html(URL)

    assert isinstance(caught.value, TransientDownloadError)
    assert len(scripted["calls"]) == 1


def test_404_is_permanent_and_not_retried(scripted, fake_clock) -> None:
    scripted["queue"] = [Response(404)]

    with pytest.raises(DownloadError) as caught:
        polite(fake_clock).fetch_html(URL)

    assert not isinstance(caught.value, (TransientDownloadError, CrawlBlockedError))
    assert len(scripted["calls"]) == 1


# --- Pausen ---------------------------------------------------------------


def test_every_request_to_hikr_keeps_the_minimum_pause(scripted, fake_clock, tmp_path: Path) -> None:
    scripted["queue"] = [
        Response(200, text="seite 1"),
        Response(200, text="seite 2"),
        Response(200, content=GPX_BYTES),
    ]
    downloader = polite(fake_clock, retry=None)

    downloader.fetch_html(URL)
    downloader.fetch_html(URL + "?skip=10")
    downloader.download_gpx(GPX_URL, title="Testtour", save_dir=tmp_path)

    assert fake_clock.sleeps == [pytest.approx(MIN_DELAY_SECONDS)] * 2


def test_existing_gpx_file_needs_no_request(scripted, fake_clock, tmp_path: Path) -> None:
    (tmp_path / "2026-07-12-testtour.gpx").write_bytes(GPX_BYTES)

    path = polite(fake_clock).download_gpx(
        GPX_URL, title="Testtour", date_iso="2026-07-12", save_dir=tmp_path
    )

    assert path.read_bytes() == GPX_BYTES
    assert scripted["calls"] == []


# --- robots.txt -----------------------------------------------------------


def test_robots_disallow_prevents_the_request(scripted, fake_clock) -> None:
    robots_text = (FIXTURES / "robots.txt").read_text(encoding="utf-8")
    robots = RobotsPolicy("Mozilla/5.0", lambda url: (200, robots_text))

    with pytest.raises(CrawlBlockedError, match="robots.txt"):
        polite(fake_clock, robots=robots).fetch_html("https://www.hikr.org/user/jemand/ski/")

    assert scripted["calls"] == []


def test_unreachable_robots_blocks_every_request(scripted, fake_clock) -> None:
    robots = RobotsPolicy("Mozilla/5.0", lambda url: (503, ""))

    with pytest.raises(CrawlBlockedError):
        polite(fake_clock, robots=robots).fetch_html(URL)

    assert scripted["calls"] == []


def test_robots_is_fetched_first_and_through_the_limiter(scripted, fake_clock) -> None:
    robots_text = (FIXTURES / "robots.txt").read_text(encoding="utf-8")
    scripted["queue"] = [Response(200, text=robots_text), Response(200, text="seite")]
    downloader = polite(fake_clock)
    downloader.robots = RobotsPolicy(downloader.headers["User-Agent"], downloader.fetch_robots)

    assert downloader.fetch_html(URL) == "seite"
    assert scripted["calls"] == [ROBOTS_URL, URL]
    assert fake_clock.sleeps == [pytest.approx(MIN_DELAY_SECONDS)]


# --- Der Downloader fuer echte Laeufe -------------------------------------


def test_polite_downloader_is_throttled_and_keeps_the_browser_headers() -> None:
    downloader = build_polite_downloader()

    assert downloader.limiter.min_interval == MIN_DELAY_SECONDS
    assert downloader.retry is not None
    assert downloader.robots is not None
    assert downloader.headers["User-Agent"].startswith("Mozilla/5.0")


def test_polite_downloader_refuses_shorter_pauses() -> None:
    with pytest.raises(ValueError):
        build_polite_downloader(1.0)


def test_building_the_polite_downloader_makes_no_request(scripted) -> None:
    build_polite_downloader()

    assert scripted["calls"] == []
