from pathlib import Path

import pytest
import requests

import main as main_module
from crawler.discovery import DiscoveryError, DiscoveryResult, ListingEntry
from crawler.downloader import CrawlBlockedError
from storage import TourStore


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
  <h1 class="title">Testskitour</h1>
  <table class="fiche_rando">
    <tr><td class="fiche_rando_b">Tour Datum:</td><td class="fiche_rando">12 Juli 2026</td></tr>
    <tr><td class="fiche_rando_b">Ski Schwierigkeit:</td><td class="fiche_rando">WS</td></tr>
  </table>
  <div id="main_text">Aufstieg und Abfahrt.</div>
  <a href="https://f.hikr.org/files/gps71129.gpx">gpx</a>
</body></html>
"""

HTML_WITHOUT_GPX = HTML.replace('<a href="https://f.hikr.org/files/gps71129.gpx">gpx</a>', "")


def post(number: int) -> str:
    return f"https://www.hikr.org/tour/post{number}.html"


class Response:
    def __init__(self, status_code: int = 200, text: str = "", content: bytes | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers: dict = {}


@pytest.fixture
def hikr(monkeypatch):
    """
    Nachbau von Hikr fuer run_tours: HTML je URL, ein Statuscode je URL
    oder GPX fuer jede .gpx Adresse. Steht eine .gpx Adresse in pages,
    liefert sie deren Text statt einer GPX Datei. requested haelt jede
    Anfrage fest.
    """
    state = {"pages": {}, "status": {}, "requested": []}

    def _get(url, headers=None, timeout=None):
        state["requested"].append(url)
        if url in state["status"]:
            return Response(state["status"][url])
        if url in state["pages"]:
            return Response(text=state["pages"][url])
        if url.lower().endswith(".gpx"):
            return Response(content=GPX_BYTES)
        raise requests.ConnectionError(f"unbekannte URL {url}")

    monkeypatch.setattr("crawler.downloader.requests.get", _get)
    return state


@pytest.fixture
def store(tmp_path: Path):
    with TourStore(tmp_path / "tours.sqlite3") as opened:
        yield opened


def run(tmp_path: Path, urls: list[str], store: TourStore):
    return main_module.run_tours(
        urls, html_dir=tmp_path / "html", gpx_dir=tmp_path / "gpx", delay=0, database=store
    )


# --- Nichts wird doppelt gecrawlt -----------------------------------------


def test_stored_and_failed_urls_are_skipped_without_a_request(tmp_path, hikr, store) -> None:
    store.upsert_tour({"source_url": post(1), "title": "schon da"})
    store.record_url_status(post(2), "fehlgeschlagen")
    hikr["pages"][post(3)] = HTML_WITHOUT_GPX

    results, failures = run(tmp_path, [post(1), post(2), post(3)], store)

    assert hikr["requested"] == [post(3)]
    assert [entry["source_url"] for entry in results] == [post(3)]
    assert failures == []
    assert store.url_status(post(3)) == "gespeichert"


def test_second_run_over_the_same_urls_requests_nothing(tmp_path, hikr, store) -> None:
    hikr["pages"][post(1)] = HTML
    run(tmp_path, [post(1)], store)
    hikr["requested"].clear()

    results, failures = run(tmp_path, [post(1)], store)

    assert hikr["requested"] == []
    assert results == []
    assert failures == []


def test_permanent_failures_are_remembered_transient_ones_are_not(tmp_path, hikr, store) -> None:
    hikr["status"][post(404)] = 404  # dauerhaft
    # post(500) steht in keiner Tabelle, der Nachbau wirft einen Netzfehler

    run(tmp_path, [post(404), post(500)], store)

    assert store.url_status(post(404)) == "fehlgeschlagen"
    assert store.skip_reason(post(404)) is not None
    assert store.url_status(post(500)) is None
    assert store.skip_reason(post(500)) is None


def test_blocked_access_ends_the_run_and_leaves_the_rest_open(tmp_path, hikr, store) -> None:
    hikr["pages"][post(1)] = HTML_WITHOUT_GPX
    hikr["status"][post(2)] = 403
    hikr["pages"][post(3)] = HTML_WITHOUT_GPX

    results, failures = run(tmp_path, [post(1), post(2), post(3)], store)

    assert post(3) not in hikr["requested"]
    assert len(results) == 1
    assert isinstance(failures[0][1], CrawlBlockedError)
    assert store.url_status(post(2)) is None
    assert store.url_status(post(3)) is None


def test_three_failures_in_a_row_end_the_run(tmp_path, hikr, store) -> None:
    urls = [post(n) for n in range(1, 6)]
    for url in urls:
        hikr["status"][url] = 404

    results, failures = run(tmp_path, urls, store)

    assert hikr["requested"] == urls[:3]
    assert len(failures) == 3


# --- Discovery Lauf -------------------------------------------------------


class FakeDiscovery:
    """Liefert vorbereitete Eintraege, beachtet is_known und protokolliert jeden Aufruf."""

    def __init__(self, entries=(), completed: bool = False, resume_skip: int = 0) -> None:
        self.entries = list(entries)
        self.completed = completed
        self.resume_skip = resume_skip
        self.calls: list[dict] = []

    def discover(self, region, kategorie, max_results, von=None, bis=None,
                 is_known=None, start_skip=0, stop_at_known_page=False, schwierigkeit=None,
                 tourtyp=None):
        self.calls.append(
            {
                "region": region, "kategorie": kategorie, "max_results": max_results,
                "von": von, "bis": bis, "start_skip": start_skip,
                "stop_at_known_page": stop_at_known_page, "schwierigkeit": schwierigkeit,
                "tourtyp": tourtyp,
            }
        )
        found = [entry for entry in self.entries if not (is_known and is_known(entry.url))]
        return DiscoveryResult(
            region, kategorie, von, bis, found=found[:max_results],
            resume_skip=self.resume_skip, completed=self.completed, pages_read=1,
        )


def entries(*numbers: int, day: str = "2025-02-01") -> list[ListingEntry]:
    return [ListingEntry(post(number), day) for number in numbers]


def test_found_urls_are_kept_open_with_the_search_progress(store) -> None:
    discovery = FakeDiscovery(entries(1, 2, 3), resume_skip=10)

    urls = main_module.discover_urls(discovery, store, "Uri", "skitouren", 2020, 2026, max_results=5)

    assert urls == [post(1), post(2), post(3)]
    call = discovery.calls[0]
    assert (call["region"], call["kategorie"]) == (146, "ski")
    assert (call["von"], call["bis"]) == ("2020-01-01", "2026-12-31")
    assert (call["start_skip"], call["stop_at_known_page"], call["max_results"]) == (0, False, 5)
    assert store.pending_urls(146, "ski", "2020-01-01", "2026-12-31") == urls
    progress = store.get_progress(146, "ski", "2020-01-01", "2026-12-31")
    assert progress["resume_skip"] == 10
    assert progress["completed"] is False


def test_open_urls_come_first_and_only_the_rest_is_searched(store) -> None:
    store.add_discovered([(post(7), "2025-05-01"), (post(8), "2025-04-01")], 146, "ski")
    discovery = FakeDiscovery(entries(9, 10, 11, 12))

    urls = main_module.discover_urls(discovery, store, 146, "ski", 2020, 2026, max_results=5)

    assert urls == [post(7), post(8), post(9), post(10), post(11)]
    assert discovery.calls[0]["max_results"] == 3


def test_enough_open_urls_need_no_search(store) -> None:
    store.add_discovered([(post(n), "2025-01-01") for n in (1, 2, 3)], 146, "ski")
    discovery = FakeDiscovery(entries(4))

    urls = main_module.discover_urls(discovery, store, 146, "ski", None, None, max_results=2)

    assert len(urls) == 2
    assert discovery.calls == []


def test_next_run_resumes_one_page_before_the_last_position(store) -> None:
    store.save_progress(146, "ski", "2020-01-01", "2026-12-31", 90, False)
    discovery = FakeDiscovery()

    main_module.discover_urls(discovery, store, 146, "ski", 2020, 2026, max_results=20)

    assert discovery.calls[0]["start_skip"] == 80
    assert discovery.calls[0]["stop_at_known_page"] is False


def test_completed_search_only_looks_for_new_reports(store) -> None:
    store.save_progress(146, "ski", None, None, 250, True)
    discovery = FakeDiscovery(completed=False)

    main_module.discover_urls(discovery, store, 146, "ski", None, None, max_results=20)

    assert discovery.calls[0]["start_skip"] == 0
    assert discovery.calls[0]["stop_at_known_page"] is True
    assert store.get_progress(146, "ski")["completed"] is True


def test_known_urls_are_never_returned_twice(store) -> None:
    store.upsert_tour({"source_url": post(1), "title": "schon gespeichert"})
    store.add_discovered([(post(2), "2025-01-01")], 146, "alp")

    first = main_module.discover_urls(FakeDiscovery(entries(1, 2, 3)), store, 146, "ski", None, None, 10)
    second = main_module.discover_urls(FakeDiscovery(entries(1, 2, 3)), store, 146, "ski", None, None, 10)

    assert first == [post(3)]
    assert second == [post(3)]


# --- Kommandozeile --------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--region", "146"],
        ["--kategorie", "ski"],
        ["--von", "2020"],
        ["--max", "5"],
        ["--max", "0"],
        ["--nur-urls"],
        ["--schwierigkeit", "T4"],
        ["--tourtyp", "hochtour"],
    ],
)
def test_discovery_options_are_rejected_without_discover(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main_module.main(argv)

    assert caught.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [["--discover"], ["--discover", "--region", "146"], ["--discover", "--kategorie", "ski"]],
)
def test_discover_needs_region_and_category(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main_module.main(argv)

    assert caught.value.code == 2


def test_plain_start_uses_the_fixed_list_and_never_builds_a_discovery(tmp_path, monkeypatch) -> None:
    class NoDiscovery:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Ohne --discover darf keine Discovery entstehen")

    seen: dict = {}

    def fake_run(urls, **kwargs):
        seen["urls"] = list(urls)
        return [], []

    monkeypatch.setattr(main_module, "HikrDiscovery", NoDiscovery)
    monkeypatch.setattr(main_module, "run_tours", fake_run)

    code = main_module.main(["--datenbank", str(tmp_path / "tours.sqlite3")])

    assert code == 0
    assert seen["urls"] == main_module.TOUR_URLS


def test_nur_urls_lists_and_remembers_without_loading(tmp_path, monkeypatch, capsys) -> None:
    def no_run(*args, **kwargs):
        raise AssertionError("Mit --nur-urls darf keine Tour geladen werden")

    monkeypatch.setattr(main_module, "HikrDiscovery", lambda downloader: FakeDiscovery(entries(41, 42)))
    monkeypatch.setattr(main_module, "run_tours", no_run)
    database = tmp_path / "tours.sqlite3"

    code = main_module.main(
        ["--discover", "--region", "146", "--kategorie", "skitouren", "--nur-urls",
         "--datenbank", str(database)]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert post(41) in output and post(42) in output
    with TourStore(database) as opened:
        assert opened.pending_urls(146, "ski") == [post(41), post(42)]


@pytest.mark.parametrize(
    "criteria",
    [["--region", "Atlantis", "--kategorie", "ski"], ["--region", "146", "--kategorie", "ski", "--max", "101"]],
)
def test_invalid_criteria_end_with_code_2_before_any_request(tmp_path, capsys, criteria) -> None:
    code = main_module.main(["--discover", *criteria, "--datenbank", str(tmp_path / "tours.sqlite3")])

    assert code == 2
    assert "Discovery nicht moeglich" in capsys.readouterr().err


# --- Kaputte GPX Dateien --------------------------------------------------

GPX_URL = "https://f.hikr.org/files/gps71129.gpx"


@pytest.mark.parametrize(
    "broken",
    [
        {"pages": "<html><body>Datei nicht gefunden</body></html>"},
        {"status": 404},
        {"pages": "<gpx version='1.1'><trk><trkseg><trkpt lat="},
    ],
    ids=["html statt gpx", "http 404", "unlesbares gpx"],
)
def test_broken_gpx_file_keeps_the_tour(tmp_path, hikr, store, broken) -> None:
    """Ein dauerhaft kaputter Anhang darf die lesbare Tour nicht mitreissen."""
    hikr["pages"][post(1)] = HTML
    if "pages" in broken:
        hikr["pages"][GPX_URL] = broken["pages"]
    else:
        hikr["status"][GPX_URL] = broken["status"]

    results, failures = run(tmp_path, [post(1)], store)

    assert failures == []
    assert results[0]["gpx_path"] is None
    assert results[0]["distance"] is None
    stored = store.get_by_url(post(1))
    assert stored["title"] == "Testskitour"
    assert stored["difficulty_ski"] == "WS"
    assert stored["gpx_path"] is None
    assert store.url_status(post(1)) == "gespeichert"


def test_transient_gpx_failure_leaves_the_tour_open(tmp_path, hikr, store) -> None:
    """Sonst ginge die GPX Datei still verloren. Der naechste Lauf versucht es erneut."""
    hikr["pages"][post(1)] = HTML
    hikr["status"][GPX_URL] = 503

    results, failures = run(tmp_path, [post(1)], store)

    assert results == []
    assert len(failures) == 1
    assert store.get_by_url(post(1)) is None
    assert store.url_status(post(1)) is None
    assert store.skip_reason(post(1)) is None


def test_blocked_gpx_request_ends_the_run(tmp_path, hikr, store) -> None:
    hikr["pages"][post(1)] = HTML
    hikr["pages"][post(2)] = HTML_WITHOUT_GPX
    hikr["status"][GPX_URL] = 403

    results, failures = run(tmp_path, [post(1), post(2)], store)

    assert results == []
    assert isinstance(failures[0][1], CrawlBlockedError)
    assert post(2) not in hikr["requested"]
    assert store.url_status(post(1)) is None


# --- Discovery mit Filter auf die Schwierigkeit ---------------------------


def test_difficulty_filter_is_passed_on_and_kept_as_its_own_search(store) -> None:
    discovery = FakeDiscovery(entries(1, 2, day="2026-07-01"), resume_skip=20, completed=True)

    urls = main_module.discover_urls(
        discovery, store, "Uri", "wandern", 2026, 2026, max_results=10,
        schwierigkeit=["T5", "T4", "T6"],
    )

    assert urls == [post(1), post(2)]
    assert discovery.calls[0]["schwierigkeit"] == ["t4", "t5", "t6"]
    assert store.pending_urls(146, "ped:t4,t5,t6", "2026-01-01", "2026-12-31") == urls
    assert store.get_progress(146, "ped:t4,t5,t6", "2026-01-01", "2026-12-31")["completed"] is True
    assert store.get_progress(146, "ped", "2026-01-01", "2026-12-31") is None


def test_open_urls_of_an_unfiltered_search_are_not_served_to_a_filtered_one(store) -> None:
    """Sonst luede ein Lauf nach T4 bis T6 offene T2 Touren aus einem Lauf ohne Filter."""
    store.add_discovered([(post(9), "2026-07-01")], 146, "ped")
    discovery = FakeDiscovery(entries(1, day="2026-08-01"))

    urls = main_module.discover_urls(
        discovery, store, 146, "wandern", 2026, 2026, max_results=5, schwierigkeit=["T4"],
    )

    assert urls == [post(1)]


def test_schwierigkeit_on_the_command_line_reaches_the_discovery(tmp_path, monkeypatch) -> None:
    created: list[FakeDiscovery] = []

    def make(downloader):
        created.append(FakeDiscovery(entries(5)))
        return created[-1]

    monkeypatch.setattr(main_module, "HikrDiscovery", make)
    monkeypatch.setattr(main_module, "run_tours", lambda urls, **kwargs: ([], []))

    code = main_module.main(
        ["--discover", "--region", "146", "--kategorie", "wandern", "--von", "2026",
         "--bis", "2026", "--schwierigkeit", "T4", "T5", "--schwierigkeit", "T6",
         "--datenbank", str(tmp_path / "tours.sqlite3")]
    )

    assert code == 0
    assert created[0].calls[0]["schwierigkeit"] == ["t4", "t5", "t6"]


# --- Discovery mit Tourtyp -------------------------------------------------


def test_tour_type_is_passed_on_and_part_of_the_search_key(store) -> None:
    discovery = FakeDiscovery(entries(1, day="2026-08-01"), completed=True)

    urls = main_module.discover_urls(
        discovery, store, 146, "hochtouren", 2026, 2026, max_results=5,
        schwierigkeit=["ZS", "WS"], tourtyp="ski-hochtour",
    )

    assert urls == [post(1)]
    assert discovery.calls[0]["tourtyp"] == "ski-hochtour"
    progress = store.get_progress(146, "alp:ws,zs|ski-hochtour", "2026-01-01", "2026-12-31")
    assert progress["completed"] is True


def test_unknown_tour_type_is_rejected_before_the_search(store) -> None:
    discovery = FakeDiscovery(entries(1))

    with pytest.raises(DiscoveryError):
        main_module.discover_urls(discovery, store, 146, "hochtouren", tourtyp="gletscher")

    assert discovery.calls == []


@pytest.mark.parametrize("argv", [["--tourtyp", "gletscher"], ["--schwierigkeit", "alpinwandern"]])
def test_invalid_tour_type_or_grade_on_the_command_line(tmp_path, argv) -> None:
    with pytest.raises(SystemExit) as caught:
        main_module.main(
            ["--discover", "--region", "146", "--kategorie", "hochtouren", *argv,
             "--datenbank", str(tmp_path / "tours.sqlite3")]
        )

    assert caught.value.code == 2


def test_tourtyp_on_the_command_line_reaches_the_discovery(tmp_path, monkeypatch) -> None:
    created: list[FakeDiscovery] = []

    def make(downloader):
        created.append(FakeDiscovery(entries(7, day="2026-06-01")))
        return created[-1]

    monkeypatch.setattr(main_module, "HikrDiscovery", make)
    monkeypatch.setattr(main_module, "run_tours", lambda urls, **kwargs: ([], []))

    code = main_module.main(
        ["--discover", "--region", "146", "--kategorie", "hochtouren",
         "--tourtyp", "alpinwandern-hochtour", "--schwierigkeit", "WS",
         "--datenbank", str(tmp_path / "tours.sqlite3")]
    )

    assert code == 0
    assert created[0].calls[0]["tourtyp"] == "alpinwandern-hochtour"
    assert created[0].calls[0]["schwierigkeit"] == ["ws"]
