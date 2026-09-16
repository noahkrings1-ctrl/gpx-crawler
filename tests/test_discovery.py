from datetime import date
from pathlib import Path

import pytest
import requests

from crawler.discovery import (
    DEFAULT_MAX_RESULTS,
    MAX_PAGES_PER_CALL,
    MAX_RESULTS_LIMIT,
    DiscoveryError,
    HikrDiscovery,
    date_bounds,
    parse_listing,
    parse_listing_date,
    resolve_category,
    resolve_region,
)
from crawler.downloader import CrawlBlockedError, DownloadError, Downloader
from crawler.politeness import MIN_DELAY_SECONDS, RateLimiter, RetryPolicy, RobotsPolicy


FIXTURES = Path(__file__).parent / "fixtures" / "hikr"
SKI = "https://www.hikr.org/region146/ski/"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def post(number: int) -> str:
    return f"https://www.hikr.org/tour/post{number}.html"


class FakeDownloader:
    """
    Liefert je URL eine Fixture und merkt sich jede Anfrage. Das Attribut
    limiter kennzeichnet ihn als gedrosselt, wie es die Discovery verlangt.
    """

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = pages or {}
        self.requested: list[str] = []
        self.limiter = object()

    def fetch_html(self, url: str) -> str:
        self.requested.append(url)
        if url not in self.pages:
            raise DownloadError(f"Failed to fetch {url}: HTTP 404")
        return self.pages[url]


@pytest.fixture
def ski_pages() -> FakeDownloader:
    return FakeDownloader(
        {
            SKI: fixture("ski_seite_1.html"),
            SKI + "?skip=10": fixture("ski_seite_2.html"),
            SKI + "?skip=20": fixture("ski_seite_3.html"),
        }
    )


# --- Grenzen --------------------------------------------------------------


def test_limits_match_the_agreement() -> None:
    assert DEFAULT_MAX_RESULTS == 20
    assert MAX_RESULTS_LIMIT == 100
    assert MAX_PAGES_PER_CALL == 20


# --- Region, Kategorie, Datum ---------------------------------------------


@pytest.mark.parametrize("value", [146, "146", " 146 ", "Uri", "uri", " URI "])
def test_region_as_id_or_name(value) -> None:
    assert resolve_region(value) == 146


def test_region_names_ignore_umlaut_spelling() -> None:
    assert resolve_region("Graubünden") == 4
    assert resolve_region("graubuenden") == 4
    assert resolve_region("St. Gallen") == 45
    assert resolve_region("Österreich") == 33


def test_unknown_region_points_to_the_id() -> None:
    with pytest.raises(DiscoveryError, match="region146.html"):
        resolve_region("Atlantis")


@pytest.mark.parametrize("value", [0, -3, True])
def test_region_id_must_be_positive(value) -> None:
    with pytest.raises(DiscoveryError):
        resolve_region(value)


def test_category_as_name_or_code() -> None:
    assert resolve_category("Skitouren") == "ski"
    assert resolve_category("skitour") == "ski"
    assert resolve_category("ski") == "ski"
    assert resolve_category("alle") == "tour"
    assert resolve_category("Schneeschuhe") == "raq"


def test_unknown_category_lists_the_allowed_ones() -> None:
    with pytest.raises(DiscoveryError, match="skitouren"):
        resolve_category("Paragliding")


def test_years_cover_the_whole_year() -> None:
    assert date_bounds(2020, 2026) == ("2020-01-01", "2026-12-31")
    assert date_bounds("2025-06-01", None) == ("2025-06-01", None)
    assert date_bounds(None, None) == (None, None)


def test_invalid_date_bounds_are_rejected() -> None:
    with pytest.raises(DiscoveryError, match="kein Jahr"):
        date_bounds("gestern", None)
    with pytest.raises(DiscoveryError, match="liegt nach"):
        date_bounds(2026, 2020)


def test_listing_dates_with_german_short_months() -> None:
    today = date(2026, 9, 16)

    assert parse_listing_date("6 Jun 26", today) == "2026-06-06"
    assert parse_listing_date("19 Mär 26", today) == "2026-03-19"
    assert parse_listing_date("19 Maer 26", today) == "2026-03-19"
    assert parse_listing_date("25 Mai 26", today) == "2026-05-25"
    assert parse_listing_date("3 Okt 15", today) == "2015-10-03"
    assert parse_listing_date("6 Jun 2026", today) == "2026-06-06"


def test_two_digit_year_in_the_future_belongs_to_the_last_century() -> None:
    assert parse_listing_date("9 Feb 95", date(2026, 9, 16)) == "1995-02-09"


def test_unreadable_listing_dates_give_none() -> None:
    assert parse_listing_date("31 Feb 26") is None
    assert parse_listing_date("gestern") is None
    assert parse_listing_date(None) is None


# --- Listenseite lesen ----------------------------------------------------


def test_listing_page_gives_ten_unique_reports_with_dates() -> None:
    page = parse_listing(fixture("ski_seite_1.html"), 146, "ski", 0)

    assert [entry.url for entry in page.entries] == [post(n) for n in range(900001, 900011)]
    assert page.entries[0].tour_date == "2026-06-06"
    assert page.entries[7].tour_date == "2026-03-19"
    assert page.has_navigator
    assert page.next_url == SKI + "?skip=10"


def test_back_links_are_never_taken_as_next_page() -> None:
    """Seite 3 verlinkt nur zurueck auf skip=10, eine naechste Seite gibt es nicht."""
    page = parse_listing(fixture("ski_seite_3.html"), 146, "ski", 20)

    assert len(page.entries) == 5
    assert page.next_url is None


def test_next_link_with_trailing_ampersand_and_relative_report_link() -> None:
    page = parse_listing(fixture("alle_seite_1.html"), 146, "tour", 0)

    assert page.next_url == "https://www.hikr.org/region146/tour/?skip=10&"
    assert page.entries[1].url == post(900102)


def test_links_to_other_regions_or_categories_are_not_followed() -> None:
    html = (
        '<div class="navigator">'
        '<a href="https://www.hikr.org/region146/alp/?skip=10">2</a>'
        '<a href="https://www.hikr.org/region2/ski/?skip=10">2</a>'
        "</div>"
    )

    assert parse_listing(html, 146, "ski", 0).next_url is None


# --- Discovery ------------------------------------------------------------


def test_discovery_refuses_an_unthrottled_downloader() -> None:
    unthrottled = FakeDownloader()
    unthrottled.limiter = None

    with pytest.raises(DiscoveryError, match="gedrosselten"):
        HikrDiscovery(unthrottled)


@pytest.mark.parametrize("pages", [0, MAX_PAGES_PER_CALL + 1])
def test_page_limit_per_call_is_bounded(pages: int) -> None:
    with pytest.raises(DiscoveryError):
        HikrDiscovery(FakeDownloader(), max_pages=pages)


@pytest.mark.parametrize(
    "criteria",
    [
        {"max_results": 0},
        {"max_results": MAX_RESULTS_LIMIT + 1},
        {"max_results": "20"},
        {"region": "Atlantis"},
        {"kategorie": "Paragliding"},
        {"von": 2026, "bis": 2020},
    ],
)
def test_invalid_criteria_are_rejected_before_any_request(ski_pages, criteria: dict) -> None:
    arguments = {"region": 146, "kategorie": "ski", "max_results": 5, **criteria}

    with pytest.raises(DiscoveryError):
        HikrDiscovery(ski_pages).discover(**arguments)

    assert ski_pages.requested == []


def test_default_is_twenty_urls(ski_pages) -> None:
    urls = HikrDiscovery(ski_pages).find_urls(146, "skitouren")

    assert urls == [post(n) for n in range(900001, 900021)]
    assert ski_pages.requested == [SKI, SKI + "?skip=10"]


def test_stops_as_soon_as_enough_urls_are_found(ski_pages) -> None:
    result = HikrDiscovery(ski_pages).discover(146, "ski", max_results=5)

    assert result.urls == [post(n) for n in range(900001, 900006)]
    assert ski_pages.requested == [SKI]
    assert result.resume_skip == 0
    assert result.completed is False


def test_stopping_mid_page_resumes_on_that_page(ski_pages) -> None:
    result = HikrDiscovery(ski_pages).discover(146, "ski", max_results=15)

    assert len(result.urls) == 15
    assert result.resume_skip == 10


def test_hundred_is_allowed_and_the_end_of_the_list_completes(ski_pages) -> None:
    result = HikrDiscovery(ski_pages).discover(146, "ski", max_results=MAX_RESULTS_LIMIT)

    assert len(result.urls) == 25
    assert result.completed is True
    assert result.pages_read == 3


def test_date_range_reads_the_normal_list_and_stops_below_the_start(ski_pages) -> None:
    """Die Liste ist absteigend sortiert, der erste Eintrag vor 2021 beendet die Suche."""
    result = HikrDiscovery(ski_pages).discover(146, "ski", max_results=50, von=2021, bis=2025)

    assert result.urls == [post(n) for n in range(900011, 900018)]
    assert result.completed is True
    assert ski_pages.requested == [SKI, SKI + "?skip=10"]


def test_newer_entries_than_the_range_do_not_count(ski_pages) -> None:
    result = HikrDiscovery(ski_pages).discover(146, "ski", max_results=3, bis=2025)

    assert result.urls == [post(900011), post(900012), post(900013)]


def test_ninety_between_2020_and_2026_takes_what_the_range_holds(ski_pages) -> None:
    result = HikrDiscovery(ski_pages).discover(146, "ski", max_results=90, von=2020, bis=2026)

    assert result.urls == [post(n) for n in range(900001, 900020)]
    assert result.completed is True


def test_known_urls_are_skipped_and_do_not_count(ski_pages) -> None:
    known = {post(900001), post(900002)}

    urls = HikrDiscovery(ski_pages).find_urls(146, "ski", max_results=3, is_known=known.__contains__)

    assert urls == [post(900003), post(900004), post(900005)]


def test_start_skip_begins_on_that_page(ski_pages) -> None:
    HikrDiscovery(ski_pages).discover(146, "ski", max_results=1, start_skip=15)

    assert ski_pages.requested == [SKI + "?skip=10"]


def test_negative_start_skip_is_rejected(ski_pages) -> None:
    with pytest.raises(DiscoveryError):
        HikrDiscovery(ski_pages).discover(146, "ski", start_skip=-10)


def test_page_limit_stops_and_resumes_on_the_next_page(ski_pages) -> None:
    result = HikrDiscovery(ski_pages, max_pages=1).discover(146, "ski", max_results=15)

    assert ski_pages.requested == [SKI]
    assert len(result.urls) == 10
    assert result.completed is False
    assert result.resume_skip == 10


def test_a_page_of_known_reports_ends_the_check_for_news(ski_pages) -> None:
    known = {post(n) for n in range(900001, 900011)}

    result = HikrDiscovery(ski_pages).discover(
        146, "ski", max_results=5, is_known=known.__contains__, stop_at_known_page=True
    )

    assert result.urls == []
    assert result.completed is True
    assert ski_pages.requested == [SKI]


def test_changed_page_structure_is_reported() -> None:
    broken = FakeDownloader({SKI: fixture("kaputt_ohne_eintraege.html")})

    with pytest.raises(DiscoveryError, match="Seitenstruktur"):
        HikrDiscovery(broken).discover(146, "ski")


def test_unsorted_list_is_refused_for_a_date_range() -> None:
    unsorted = FakeDownloader({SKI: fixture("unsortiert.html")})

    with pytest.raises(DiscoveryError, match="absteigend"):
        HikrDiscovery(unsorted).discover(146, "ski", von=2020)


def test_unsorted_list_is_fine_without_a_date_range() -> None:
    unsorted = FakeDownloader({SKI: fixture("unsortiert.html")})

    result = HikrDiscovery(unsorted).discover(146, "ski")

    assert len(result.urls) == 3
    assert result.completed is True


def test_listing_url() -> None:
    assert HikrDiscovery.listing_url(146, "ski") == SKI
    assert HikrDiscovery.listing_url(146, "ski", 20) == SKI + "?skip=20"


# --- Mit dem echten, gedrosselten Downloader -------------------------------


class Page:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text
        self.content = text.encode("utf-8")
        self.headers: dict = {}


def serve(monkeypatch, pages: dict[str, str]) -> list[str]:
    calls: list[str] = []

    def _get(url, headers=None, timeout=None):
        calls.append(url)
        return Page(pages[url])

    monkeypatch.setattr(requests, "get", _get)
    return calls


def real_downloader(fake_clock) -> Downloader:
    downloader = Downloader(
        limiter=RateLimiter(clock=fake_clock, sleep=fake_clock.sleep), retry=RetryPolicy()
    )
    downloader.robots = RobotsPolicy(downloader.headers["User-Agent"], downloader.fetch_robots)
    return downloader


def test_every_request_keeps_the_pause_and_robots_comes_first(monkeypatch, fake_clock) -> None:
    calls = serve(
        monkeypatch,
        {
            "https://www.hikr.org/robots.txt": fixture("robots.txt"),
            SKI: fixture("ski_seite_1.html"),
            SKI + "?skip=10": fixture("ski_seite_2.html"),
        },
    )

    urls = HikrDiscovery(real_downloader(fake_clock)).find_urls(146, "skitouren", max_results=15)

    assert len(urls) == 15
    assert calls == ["https://www.hikr.org/robots.txt", SKI, SKI + "?skip=10"]
    assert fake_clock.sleeps == [pytest.approx(MIN_DELAY_SECONDS)] * 2


def test_listing_forbidden_by_robots_is_never_requested(monkeypatch, fake_clock) -> None:
    calls = serve(
        monkeypatch,
        {"https://www.hikr.org/robots.txt": "User-agent: *\nDisallow: /region\n"},
    )

    with pytest.raises(CrawlBlockedError):
        HikrDiscovery(real_downloader(fake_clock)).find_urls(146, "ski")

    assert calls == ["https://www.hikr.org/robots.txt"]
