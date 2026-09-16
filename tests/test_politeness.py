from pathlib import Path

import pytest

from crawler.politeness import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_RETRIES,
    MAX_RETRY_AFTER_SECONDS,
    MIN_DELAY_SECONDS,
    RateLimiter,
    RetryPolicy,
    RobotsPolicy,
    domain_key,
    is_challenge,
    parse_retry_after,
)


FIXTURES = Path(__file__).parent / "fixtures" / "hikr"
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
PAGE = "https://www.hikr.org/region146/ski/"


def limiter_with(fake_clock, min_interval: float = MIN_DELAY_SECONDS) -> RateLimiter:
    return RateLimiter(min_interval, clock=fake_clock, sleep=fake_clock.sleep)


def policy(status: int, text: str = "", calls: list | None = None) -> RobotsPolicy:
    """RobotsPolicy mit vorbereiteter Antwort statt einer echten Anfrage."""

    def fetch(url: str) -> tuple[int, str]:
        if calls is not None:
            calls.append(url)
        return status, text

    return RobotsPolicy(BROWSER, fetch)


@pytest.fixture
def robots_text() -> str:
    return (FIXTURES / "robots.txt").read_text(encoding="utf-8")


# --- Grenzwerte -----------------------------------------------------------


def test_limits_are_conservative() -> None:
    assert MIN_DELAY_SECONDS == 2.0
    assert MAX_RETRIES == 2
    assert MAX_RETRY_AFTER_SECONDS == 300.0
    assert MAX_CONSECUTIVE_FAILURES == 3


# --- Drossel --------------------------------------------------------------


def test_domain_key_groups_subdomains() -> None:
    assert domain_key("https://www.hikr.org/region146/ski/") == "hikr.org"
    assert domain_key("https://f.hikr.org/files/gps1.gpx") == "hikr.org"
    assert domain_key("https://example.org/seite") == "example.org"


@pytest.mark.parametrize("too_short", [0, 1.0, 1.99])
def test_pause_below_two_seconds_is_refused(too_short: float) -> None:
    with pytest.raises(ValueError, match="nicht unterschreiten"):
        RateLimiter(too_short)


def test_first_request_does_not_wait(fake_clock) -> None:
    limiter = limiter_with(fake_clock)

    assert limiter.wait(PAGE) == 0.0
    assert fake_clock.sleeps == []


def test_second_request_waits_for_the_rest_of_the_interval(fake_clock) -> None:
    limiter = limiter_with(fake_clock)
    limiter.wait(PAGE)
    fake_clock.advance(0.5)

    limiter.wait(PAGE + "?skip=10")

    assert fake_clock.sleeps == [pytest.approx(1.5)]


def test_page_and_gpx_host_share_one_limit(fake_clock) -> None:
    """Sonst folgte die GPX Datei ohne Pause auf die Tourseite."""
    limiter = limiter_with(fake_clock)
    limiter.wait("https://www.hikr.org/tour/post1.html")

    limiter.wait("https://f.hikr.org/files/gps1.gpx")

    assert fake_clock.sleeps == [pytest.approx(2.0)]


def test_other_domains_are_throttled_separately(fake_clock) -> None:
    limiter = limiter_with(fake_clock)
    limiter.wait(PAGE)

    limiter.wait("https://example.org/seite")

    assert fake_clock.sleeps == []


def test_no_wait_after_enough_time_has_passed(fake_clock) -> None:
    limiter = limiter_with(fake_clock)
    limiter.wait(PAGE)
    fake_clock.advance(2.5)

    limiter.wait(PAGE)

    assert fake_clock.sleeps == []


def test_longer_crawl_delay_wins_shorter_one_does_not(fake_clock) -> None:
    limiter = limiter_with(fake_clock)
    limiter.wait(PAGE)

    limiter.wait(PAGE, crawl_delay=5)
    limiter.wait(PAGE, crawl_delay=1)

    assert fake_clock.sleeps == [pytest.approx(5.0), pytest.approx(2.0)]


def test_pause_uses_the_injected_sleep(fake_clock) -> None:
    limiter = limiter_with(fake_clock)

    limiter.pause(15)
    limiter.pause(0)

    assert fake_clock.sleeps == [15]


# --- Wiederholungen -------------------------------------------------------


def test_backoff_grows_and_then_stays() -> None:
    retry = RetryPolicy()

    assert retry.backoff(1) == 15.0
    assert retry.backoff(2) == 60.0
    assert retry.backoff(3) == 60.0


def test_retry_after_is_read_as_seconds_only() -> None:
    """Ein Datum im Header gilt als unbekannt, lieber aufhoeren als raten."""
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after(" 30 ") == 30.0
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert parse_retry_after("-5") is None
    assert parse_retry_after("1.5") is None
    assert parse_retry_after(None) is None


def test_cloudflare_challenge_is_recognised() -> None:
    assert is_challenge({"cf-mitigated": "challenge"})
    assert is_challenge({"CF-Mitigated": " Challenge "})
    assert not is_challenge({"cf-mitigated": "none"})
    assert not is_challenge({})


# --- robots.txt -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/region146/ski/",
        "/region146/ski/?skip=10",
        "/region146/tour/?skip=10&",
        "/tour/post900001.html",
    ],
)
def test_listing_and_tour_pages_are_allowed(robots_text: str, path: str) -> None:
    assert policy(200, robots_text).allowed("https://www.hikr.org" + path)


@pytest.mark.parametrize(
    "path",
    [
        "/user/jemand/ski/",
        "/tour/?date_year_month=2025-03",
        "/map.php",
        "/?skip=10",
    ],
)
def test_forbidden_paths_are_refused(robots_text: str, path: str) -> None:
    assert not policy(200, robots_text).allowed("https://www.hikr.org" + path)


def test_robots_is_loaded_lazily_and_once_per_host(robots_text: str) -> None:
    """Ein Lauf ohne Anfrage fragt auch robots.txt nicht ab."""
    calls: list[str] = []
    robots = policy(200, robots_text, calls)
    assert calls == []

    robots.allowed(PAGE)
    robots.allowed("https://www.hikr.org/tour/post1.html")
    robots.allowed("https://f.hikr.org/files/gps1.gpx")

    assert calls == [
        "https://www.hikr.org/robots.txt",
        "https://f.hikr.org/robots.txt",
    ]


def test_missing_robots_allows_everything() -> None:
    assert policy(404).allowed(PAGE)


@pytest.mark.parametrize("status", [0, 401, 403, 500, 503])
def test_unreachable_or_locked_robots_blocks_everything(status: int) -> None:
    """Unbekannte Regeln heissen: nicht crawlen."""
    assert not policy(status).allowed(PAGE)


def test_crawl_delay_is_read_from_robots(robots_text: str) -> None:
    assert policy(200, "User-agent: *\nCrawl-delay: 7\nAllow: /\n").crawl_delay(PAGE) == 7.0
    assert policy(200, robots_text).crawl_delay(PAGE) is None
