"""Ablage: Ski Skala, Berichtstext, Datumsbereich, bekannte URLs und Suchstand."""

import pytest

from storage import TourStore, TourStoreError


def tour(**overrides) -> dict:
    metadata = {
        "source_url": "https://www.hikr.org/tour/post1.html",
        "title": "Testtour",
        "date_iso": "2025-02-01",
        "sport": "Wandern",
    }
    metadata.update(overrides)
    return metadata


def titles(tours: list[dict]) -> set[str]:
    return {entry["title"] for entry in tours}


@pytest.fixture
def store():
    with TourStore(":memory:") as opened:
        yield opened


# --- Ski, Text und Datum --------------------------------------------------


def test_ski_difficulty_is_stored_and_searchable(store) -> None:
    store.upsert_tour(tour(source_url="https://x/ski.html", title="Skitour", sport="Skitour", difficulty_ski="ZS+"))
    store.upsert_tour(tour(source_url="https://x/alp.html", title="Hochtour", sport="Hochtour", difficulty_alpine="ZS-"))

    assert store.get_by_url("https://x/ski.html")["difficulty_ski"] == "ZS+"
    assert titles(store.find_tours(difficulty="ZS+")) == {"Skitour"}
    assert titles(store.find_tours(difficulty="ZS")) == {"Skitour", "Hochtour"}
    assert titles(store.find_tours(sport="skitour")) == {"Skitour"}


def test_text_search_covers_report_and_title(store) -> None:
    store.upsert_tour(tour(source_url="https://x/1.html", title="Ortler", main_text="Nacht im Biwak, dann weiter zur Hütte."))
    store.upsert_tour(tour(source_url="https://x/2.html", title="Biwak am Grat", main_text=None))
    store.upsert_tour(tour(source_url="https://x/3.html", title="Talwanderung", main_text="Kein Stichwort."))

    assert titles(store.find_tours(text="biwak")) == {"Ortler", "Biwak am Grat"}
    assert titles(store.find_tours(text="Huette")) == {"Ortler"}
    assert store.find_tours(text="gletscher") == []
    assert len(store.find_tours(text="  ")) == 3


def test_date_range_includes_both_ends_and_drops_undated(store) -> None:
    for url, day in [
        ("https://x/a.html", "2019-12-31"),
        ("https://x/b.html", "2020-01-01"),
        ("https://x/c.html", "2025-12-31"),
        ("https://x/d.html", "2026-01-01"),
        ("https://x/e.html", None),
    ]:
        store.upsert_tour(tour(source_url=url, title=url, date_iso=day))

    found = store.find_tours(date_from="2020-01-01", date_to="2025-12-31")

    assert {entry["source_url"] for entry in found} == {"https://x/b.html", "https://x/c.html"}
    assert len(store.find_tours(date_from="2026-01-01")) == 1


# --- Bekannte URLs --------------------------------------------------------


def test_discovered_urls_cannot_be_added_twice(store) -> None:
    first = store.add_discovered([("https://x/1.html", "2026-01-01"), ("https://x/2.html", None)], 146, "ski")
    second = store.add_discovered([("https://x/1.html", "2026-01-01"), ("https://x/3.html", "2025-01-01")], 146, "ski")

    assert first == 2
    assert second == 1
    assert store.url_status("https://x/1.html") == "neu"


def test_known_means_stored_or_discovered(store) -> None:
    store.upsert_tour(tour(source_url="https://x/gespeichert.html"))
    store.add_discovered([("https://x/gefunden.html", None)], 146, "ski")

    assert store.is_known_url("https://x/gespeichert.html")
    assert store.is_known_url("https://x/gefunden.html")
    assert not store.is_known_url("https://x/unbekannt.html")


def test_skip_reason_for_stored_and_failed_urls_only(store) -> None:
    store.upsert_tour(tour(source_url="https://x/gespeichert.html"))
    store.record_url_status("https://x/404.html", "fehlgeschlagen")
    store.add_discovered([("https://x/offen.html", None)], 146, "ski")

    assert store.skip_reason("https://x/gespeichert.html") == "bereits gespeichert"
    assert "fehlgeschlagen" in store.skip_reason("https://x/404.html")
    assert store.skip_reason("https://x/offen.html") is None
    assert store.skip_reason("https://x/unbekannt.html") is None


def test_unknown_status_is_rejected(store) -> None:
    with pytest.raises(TourStoreError, match="Unbekannter Status"):
        store.record_url_status("https://x/1.html", "vielleicht")


def test_stored_url_is_no_longer_pending(store) -> None:
    store.add_discovered([("https://x/1.html", "2026-01-01")], 146, "ski")

    store.record_url_status("https://x/1.html", "gespeichert")

    assert store.url_status("https://x/1.html") == "gespeichert"
    assert store.pending_urls(146, "ski") == []


def test_pending_urls_belong_to_one_search_newest_first(store) -> None:
    store.add_discovered(
        [
            ("https://x/2023.html", "2023-05-01"),
            ("https://x/2026.html", "2026-02-01"),
            ("https://x/ohne.html", None),
            ("https://x/2019.html", "2019-03-01"),
        ],
        146,
        "ski",
    )
    store.add_discovered([("https://x/alp.html", "2024-01-01")], 146, "alp")
    store.add_discovered([("https://x/bern.html", "2024-01-01")], 13, "ski")

    assert store.pending_urls(146, "ski") == [
        "https://x/2026.html",
        "https://x/2023.html",
        "https://x/2019.html",
        "https://x/ohne.html",
    ]
    assert store.pending_urls(146, "ski", "2020-01-01", "2025-12-31") == ["https://x/2023.html"]
    assert store.pending_urls(146, "ski", limit=2) == ["https://x/2026.html", "https://x/2023.html"]


# --- Suchstand ------------------------------------------------------------


def test_progress_is_kept_per_search(store) -> None:
    assert store.get_progress(146, "ski", "2020-01-01", "2026-12-31") is None

    store.save_progress(146, "ski", "2020-01-01", "2026-12-31", 90, False)

    assert store.get_progress(146, "ski", "2020-01-01", "2026-12-31")["resume_skip"] == 90
    assert store.get_progress(146, "ski") is None
    assert store.get_progress(146, "alp", "2020-01-01", "2026-12-31") is None


def test_completed_search_stays_completed(store) -> None:
    store.save_progress(146, "ski", None, None, 250, True)
    store.save_progress(146, "ski", None, None, 0, False)

    progress = store.get_progress(146, "ski")

    assert progress["completed"] is True
    assert progress["resume_skip"] == 0
