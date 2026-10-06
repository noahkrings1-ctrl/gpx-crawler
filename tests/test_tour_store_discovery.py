"""Ablage: Ski Skala, Berichtstext, Datumsbereich, bekannte URLs und Suchstand."""

import sqlite3
from pathlib import Path

import pytest

from storage import TourStore, TourStoreError
from storage.tour_store import SCHEMA, STATUS_NO_GPX


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
    store.record_url_status("https://x/ohne.html", STATUS_NO_GPX)
    store.add_discovered([("https://x/offen.html", None)], 146, "ski")

    assert store.skip_reason("https://x/gespeichert.html") == "bereits gespeichert"
    assert "fehlgeschlagen" in store.skip_reason("https://x/404.html")
    assert store.skip_reason("https://x/ohne.html") == "hat keine GPX Datei"
    assert store.skip_reason("https://x/offen.html") is None
    assert store.skip_reason("https://x/unbekannt.html") is None


def test_a_tour_without_gpx_counts_as_known(store) -> None:
    """Sonst wuerde die Discovery dieselbe URL wieder ausliefern."""
    store.record_url_status("https://x/ohne.html", STATUS_NO_GPX)

    assert store.is_known_url("https://x/ohne.html")
    assert store.url_status("https://x/ohne.html") == STATUS_NO_GPX


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


# --- Exakte Stufen und Tourtypen -------------------------------------------


@pytest.fixture
def alpine_store(store):
    store.upsert_tour(tour(source_url="https://x/ski.html", title="Ski und Hochtour",
                           sport="Skitour", difficulty_alpine="WS", difficulty_ski="ZS"))
    store.upsert_tour(tour(source_url="https://x/alpin.html", title="Alpinwandern und Hochtour",
                           sport="Hochtour", difficulty_hiking="T5- - anspruchsvolles Alpinwandern",
                           difficulty_alpine="WS"))
    store.upsert_tour(tour(source_url="https://x/hoch.html", title="Reine Hochtour",
                           sport="Hochtour", difficulty_hiking="T3 - anspruchsvolles Bergwandern",
                           difficulty_alpine="S"))
    store.upsert_tour(tour(source_url="https://x/klettern.html", title="Kletterei",
                           sport="Klettern", difficulty_climbing="III (UIAA-Skala)"))
    store.upsert_tour(tour(source_url="https://x/wandern.html", title="Wanderung",
                           sport="Wandern", difficulty_hiking="T4 - Alpinwandern"))
    return store


@pytest.mark.parametrize(
    "tour_type, expected",
    [
        ("ski-hochtour", {"Ski und Hochtour"}),
        ("alpinwandern-hochtour", {"Alpinwandern und Hochtour"}),
        ("hochtour", {"Reine Hochtour"}),
    ],
)
def test_tour_type_filter(alpine_store, tour_type, expected) -> None:
    assert titles(alpine_store.find_tours(tour_type=tour_type)) == expected


def test_grade_is_compared_exactly_not_as_text(alpine_store) -> None:
    assert titles(alpine_store.find_tours(difficulty="S")) == {"Reine Hochtour"}
    assert titles(alpine_store.find_tours(difficulty="II")) == set()
    assert titles(alpine_store.find_tours(difficulty="III")) == {"Kletterei"}
    assert titles(alpine_store.find_tours(difficulty="T5")) == {"Alpinwandern und Hochtour"}


def test_grade_matches_on_any_scale_and_combines_with_tour_type(alpine_store) -> None:
    assert titles(alpine_store.find_tours(difficulty="ZS")) == {"Ski und Hochtour"}
    assert titles(alpine_store.find_tours(difficulty="WS", tour_type="alpinwandern-hochtour")) == {
        "Alpinwandern und Hochtour"
    }


def test_unknown_tour_type_or_grade_is_rejected(alpine_store) -> None:
    with pytest.raises(TourStoreError, match="Tourtyp"):
        alpine_store.find_tours(tour_type="gletscher")
    with pytest.raises(TourStoreError, match="keine Schwierigkeitsstufe"):
        alpine_store.find_tours(difficulty="alpinwandern")

# --- Umbau einer aelteren Ablage ---------------------------------------------

# Die Tabelle, wie sie vor dem Status ohne_gpx aussah.
ALTE_TABELLE = """
CREATE TABLE discovered_urls (
    url                 TEXT PRIMARY KEY,
    region_id           INTEGER,
    category            TEXT,
    tour_date           TEXT,
    status              TEXT NOT NULL
                        CHECK (status IN ('neu', 'gespeichert', 'fehlgeschlagen')),
    first_seen          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_discovered_search
    ON discovered_urls (region_id, category, status, tour_date);
"""


def alte_ablage(path: Path) -> None:
    """Legt eine Ablage im Stand vor dem neuen Status an, mit einer URL darin."""
    connection = sqlite3.connect(path)
    connection.executescript(ALTE_TABELLE)
    connection.execute(
        "INSERT INTO discovered_urls VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://x/alt.html", 146, "ski", "2025-03-01", "neu", "frueher", "frueher"),
    )
    connection.commit()
    connection.close()


def test_the_old_table_really_rejects_the_new_status(tmp_path: Path) -> None:
    """Voraussetzung des Umbaus: ohne ihn liesse sich ohne_gpx nicht ablegen."""
    target = tmp_path / "alt.sqlite3"
    alte_ablage(target)
    connection = sqlite3.connect(target)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO discovered_urls VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("https://x/neu.html", 146, "ski", None, STATUS_NO_GPX, "jetzt", "jetzt"),
        )
    connection.close()


def test_an_older_database_is_rebuilt_and_keeps_its_rows(tmp_path: Path) -> None:
    target = tmp_path / "alt.sqlite3"
    alte_ablage(target)

    with TourStore(target) as store:
        store.record_url_status("https://x/ohne.html", STATUS_NO_GPX)

        alt = store.connection.execute(
            "SELECT * FROM discovered_urls WHERE url = ?", ("https://x/alt.html",)
        ).fetchone()
        assert alt["status"] == "neu"
        assert alt["region_id"] == 146
        assert alt["category"] == "ski"
        assert alt["tour_date"] == "2025-03-01"
        assert alt["first_seen"] == "frueher"
        assert store.pending_urls(146, "ski") == ["https://x/alt.html"]
        assert store.url_status("https://x/ohne.html") == STATUS_NO_GPX

        namen = {
            row["name"]
            for row in store.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", ("index",)
            )
        }
        assert "idx_discovered_search" in namen
        uebrig = store.connection.execute(
            "SELECT name FROM sqlite_master WHERE name = ?", ("discovered_urls_neu",)
        ).fetchone()
        assert uebrig is None


def test_a_current_database_is_left_alone(tmp_path: Path) -> None:
    target = tmp_path / "aktuell.sqlite3"
    with TourStore(target) as store:
        store.record_url_status("https://x/1.html", STATUS_NO_GPX)
        vorher = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", ("discovered_urls",)
        ).fetchone()["sql"]

    with TourStore(target) as store:
        nachher = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", ("discovered_urls",)
        ).fetchone()["sql"]
        assert nachher == vorher
        assert store.url_status("https://x/1.html") == STATUS_NO_GPX


# --- Schneeschuhskala ---------------------------------------------------------


def test_the_snowshoe_grade_is_stored_and_searchable(store) -> None:
    store.upsert_tour(tour(source_url="https://x/wt.html", title="Schneeschuhtour",
                           sport="Schneeschuhtour", difficulty_snowshoe="WT3 - Anspruchsvolle Schneeschuhwanderung"))
    store.upsert_tour(tour(source_url="https://x/ski.html", title="Skitour",
                           sport="Skitour", difficulty_ski="WS"))

    assert store.get_by_url("https://x/wt.html")["difficulty_snowshoe"].startswith("WT3")
    assert titles(store.find_tours(difficulty="WT3")) == {"Schneeschuhtour"}
    assert titles(store.find_tours(difficulty="WT4")) == set()
    assert titles(store.find_tours(sport="Schneeschuhtour")) == {"Schneeschuhtour"}


def test_an_older_database_gets_the_new_column(tmp_path: Path) -> None:
    """
    CREATE TABLE IF NOT EXISTS laesst eine bestehende Tabelle in Ruhe.

    Ohne ALTER TABLE kaeme die Spalte in einer gewachsenen Ablage nie an.
    """
    target = tmp_path / "alt.sqlite3"
    # Das heutige Schema ohne die neue Spalte ist genau der alte Stand.
    alt = SCHEMA.replace("    difficulty_snowshoe TEXT,\n", "")
    assert "difficulty_snowshoe" not in alt

    connection = sqlite3.connect(target)
    connection.executescript(alt)
    connection.execute(
        "INSERT INTO tours (source_url, title, created_at, updated_at) "
        "VALUES ('https://x/alt.html', 'Alte Tour', 'frueher', 'frueher')"
    )
    connection.commit()
    connection.close()

    with TourStore(target) as store:
        spalten = {row["name"] for row in store.connection.execute("PRAGMA table_info(tours)")}

        assert "difficulty_snowshoe" in spalten
        assert store.get_by_url("https://x/alt.html")["title"] == "Alte Tour"
        assert store.get_by_url("https://x/alt.html")["difficulty_snowshoe"] is None


def test_the_guard_catches_the_default_path() -> None:
    """Voraussetzung: Ein Test, der die echte Ablage oeffnet, faellt auf."""
    with pytest.raises(AssertionError, match="Tests muessen tmp_path"):
        TourStore()
