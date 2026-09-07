import sqlite3
from pathlib import Path

import pytest

from storage import TourDatabase


def sample(**overrides) -> dict:
    """Metadaten, wie sie der Parser und main.py liefern."""
    metadata = {
        "source_url": "https://www.hikr.org/tour/post203736.html",
        "title": "Ortler via neue Olaf Reinstadler-Route",
        "region": "Welt , Italien , Trentino-Suedtirol",
        "region_leaf": "Trentino-Suedtirol",
        "date": "29 August 2026",
        "date_iso": "2026-08-29",
        "sport": "Hochtour",
        "difficulty_hiking": "T4 - Alpinwandern",
        "difficulty_alpine": "ZS-",
        "difficulty_climbing": "III (UIAA-Skala)",
        "elevation_gain_m": 1700,
        "elevation_loss_m": 1700,
        "time_required": "2 Tage",
        "time_required_min": None,
        "duration_days": 2,
        "distance": 19.06,
        "language": None,
        "gpx_url": "https://f.hikr.org/files/gps71800.gpx",
        "gpx_path": "data/gpx/2026-08-29-ortler.gpx",
    }
    metadata.update(overrides)
    return metadata


@pytest.fixture
def database(tmp_path: Path):
    with TourDatabase(tmp_path / "tours.sqlite3") as db:
        yield db


def test_schema_is_created_on_enter(database) -> None:
    tables = database.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()

    assert "tours" in [row["name"] for row in tables]
    assert database.count() == 0


def test_upsert_stores_all_fields(database) -> None:
    database.upsert_tour(sample())
    stored = database.get_by_url(sample()["source_url"])

    assert stored["title"] == "Ortler via neue Olaf Reinstadler-Route"
    assert stored["sport"] == "Hochtour"
    assert stored["elevation_gain_m"] == 1700
    assert stored["duration_days"] == 2
    assert stored["time_required_min"] is None
    # Im Dictionary heisst das Feld distance, in der Tabelle distance_km.
    assert stored["distance_km"] == pytest.approx(19.06)
    assert stored["created_at"] and stored["updated_at"]


def test_second_run_updates_instead_of_duplicating(database) -> None:
    """Die Quelle URL ist der Schluessel, ein zweiter Lauf legt nichts doppelt an."""
    database.upsert_tour(sample())
    first = database.get_by_url(sample()["source_url"])

    database.upsert_tour(sample(title="Ortler, korrigierter Titel", distance=19.42))

    assert database.count() == 1
    updated = database.get_by_url(sample()["source_url"])
    assert updated["title"] == "Ortler, korrigierter Titel"
    assert updated["distance_km"] == pytest.approx(19.42)
    assert updated["id"] == first["id"]
    # Der Zeitpunkt des ersten Fundes darf nicht verloren gehen.
    assert updated["created_at"] == first["created_at"]


def test_missing_source_url_is_rejected(database) -> None:
    with pytest.raises(ValueError, match="source_url"):
        database.upsert_tour(sample(source_url=None))


def test_partial_metadata_is_accepted(database) -> None:
    """Eine Tour ohne Datum, Distanz und Schwierigkeit muss trotzdem hineinpassen."""
    database.upsert_tour({"source_url": "https://www.hikr.org/tour/post1.html"})

    stored = database.get_by_url("https://www.hikr.org/tour/post1.html")
    assert stored["title"] is None
    assert stored["distance_km"] is None
    assert database.count() == 1


def test_all_tours_sorts_by_date_and_puts_undated_last(database) -> None:
    database.upsert_tour(sample(source_url="https://x/2.html", date_iso="2026-08-29"))
    database.upsert_tour(sample(source_url="https://x/1.html", date_iso="2023-06-18"))
    database.upsert_tour(sample(source_url="https://x/3.html", date_iso=None))

    dates = [tour["date_iso"] for tour in database.all_tours()]

    assert dates == ["2023-06-18", "2026-08-29", None]


def test_database_file_is_created_with_missing_folder(tmp_path: Path) -> None:
    target = tmp_path / "noch" / "nicht" / "da" / "tours.sqlite3"

    with TourDatabase(target) as db:
        db.upsert_tour(sample())

    assert target.exists()


def test_data_survives_reopening(tmp_path: Path) -> None:
    target = tmp_path / "tours.sqlite3"
    with TourDatabase(target) as db:
        db.upsert_tour(sample())

    with TourDatabase(target) as db:
        assert db.count() == 1
        assert db.all_tours()[0]["sport"] == "Hochtour"


def test_use_without_connection_raises(tmp_path: Path) -> None:
    db = TourDatabase(tmp_path / "tours.sqlite3")

    with pytest.raises(RuntimeError, match="Keine Verbindung"):
        db.count()
