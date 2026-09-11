import argparse
from pathlib import Path

import pytest

import query
from storage import TourStore


def tour(**overrides) -> dict:
    """Ein Datensatz, wie ihn die Ablage zurueckgibt."""
    metadata = {
        "source_url": "https://www.hikr.org/tour/post1.html",
        "title": "Ronengrat und Klettergarten Gummen",
        "region": "Welt , Schweiz , Nidwalden",
        "region_country": "Schweiz",
        "region_main": "Nidwalden",
        "region_area": None,
        "region_leaf": "Nidwalden",
        "date": "2 September 2026",
        "date_iso": "2026-09-02",
        "sport": "Wandern",
        "difficulty_hiking": "T4 - Alpinwandern",
        "difficulty_alpine": None,
        "difficulty_climbing": "III (UIAA-Skala)",
        "elevation_gain_m": 1380,
        "elevation_loss_m": 1380,
        "time_required": "4:00",
        "time_required_min": 240,
        "duration_days": None,
        "distance": 24.17,
        "language": None,
        "gpx_url": None,
        "gpx_path": None,
    }
    metadata.update(overrides)
    return metadata


def as_row(**overrides) -> dict:
    """Wie tour, aber mit dem Spaltennamen distance_km statt distance."""
    row = tour(**overrides)
    row["distance_km"] = row.pop("distance")
    return row


@pytest.fixture
def filled_database(tmp_path: Path) -> Path:
    """Eine echte Datei, weil query.main ihre Existenz prueft."""
    target = tmp_path / "tours.sqlite3"
    with TourStore(target) as store:
        store.upsert_tour(tour())
        store.upsert_tour(
            tour(
                source_url="https://www.hikr.org/tour/post2.html",
                title="Meraner Hoehenweg",
                region_country="Italien",
                region_main="Trentino-Suedtirol",
                region_leaf="Trentino-Suedtirol",
                date_iso="2023-06-18",
                difficulty_hiking="T2 - Bergwandern",
                difficulty_climbing=None,
                elevation_gain_m=None,
                time_required="6 Tage",
                time_required_min=None,
                duration_days=6,
                distance=92.98,
            )
        )
    return target


# --- Dauer lesen und schreiben ------------------------------------------


def test_parse_duration_accepts_hours_and_minutes() -> None:
    assert query.parse_duration("5:30") == 330
    assert query.parse_duration("0:45") == 45
    assert query.parse_duration("10:00") == 600


def test_parse_duration_accepts_plain_minutes() -> None:
    """Auf der Kommandozeile ist beides naheliegend."""
    assert query.parse_duration("330") == 330
    assert query.parse_duration(" 90 ") == 90


def test_parse_duration_rejects_nonsense() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="keine Dauer"):
        query.parse_duration("gestern")


def test_format_duration_shows_hours_days_or_nothing() -> None:
    assert query.format_duration(as_row(time_required_min=330)) == "5:30"
    assert query.format_duration(as_row(time_required_min=240)) == "4:00"
    assert query.format_duration(as_row(time_required_min=45)) == "0:45"
    assert (
        query.format_duration(as_row(time_required_min=None, duration_days=6))
        == "6 Tage"
    )
    assert (
        query.format_duration(as_row(time_required_min=None, duration_days=None)) == "-"
    )


def test_format_region_falls_back_to_the_country() -> None:
    assert query.format_region(as_row()) == "Nidwalden"
    assert query.format_region(as_row(region_main=None)) == "Schweiz"
    assert query.format_region(as_row(region_main=None, region_country=None)) == "-"


def test_format_difficulty_prefers_the_alpine_scale() -> None:
    """Dieselbe Rangfolge wie bei der Sportart im Parser."""
    assert query.format_difficulty(as_row(difficulty_alpine="ZS-")) == "ZS-"
    assert query.format_difficulty(as_row()) == "T4 - Alpinwandern"
    assert (
        query.format_difficulty(as_row(difficulty_hiking=None)) == "III (UIAA-Skala)"
    )
    assert (
        query.format_difficulty(
            as_row(difficulty_hiking=None, difficulty_climbing=None)
        )
        == "-"
    )


# --- Tabelle ------------------------------------------------------------


def test_table_without_rows_says_so() -> None:
    assert query.format_table([]) == "Keine Tour gefunden."


def test_table_has_a_header_and_a_count() -> None:
    table = query.format_table([as_row()])

    assert "Datum" in table and "Schwierigkeit" in table and "Titel" in table
    assert "Ronengrat und Klettergarten Gummen" in table
    assert "1380 m" in table
    assert "24.17 km" in table
    assert table.rstrip().endswith("1 Tour gefunden.")


def test_table_counts_in_plural() -> None:
    table = query.format_table([as_row(), as_row(source_url="https://x/2.html")])

    assert table.rstrip().endswith("2 Touren gefunden.")


def test_table_shows_a_dash_for_missing_values() -> None:
    table = query.format_table(
        [as_row(distance_km=None, elevation_gain_m=None, date_iso=None)]
    )

    assert " - " in table


def test_table_lines_have_no_trailing_spaces() -> None:
    """Die letzte Spalte wird nicht aufgefuellt, sonst haengen Leerzeichen an."""
    table = query.format_table([as_row(), as_row(source_url="https://x/2.html")])

    for line in table.splitlines():
        assert line == line.rstrip()


# --- Argumente ----------------------------------------------------------


def test_parser_defaults_are_all_empty() -> None:
    args = query.build_parser().parse_args([])

    assert args.region is None
    assert args.sportart is None
    assert args.schwierigkeit is None
    assert args.min_aufstieg is None
    assert args.max_aufstieg is None
    assert args.max_dauer is None
    assert args.sortierung == "date_iso"
    assert args.absteigend is False
    assert args.limit is None


def test_parser_reads_all_filters() -> None:
    args = query.build_parser().parse_args(
        [
            "--region", "Uri",
            "--sportart", "Wandern",
            "--schwierigkeit", "T4",
            "--min-aufstieg", "800",
            "--max-aufstieg", "1500",
            "--max-dauer", "5:30",
            "--sortierung", "distance_km",
            "--absteigend",
            "--limit", "3",
        ]
    )

    assert args.region == "Uri"
    assert args.schwierigkeit == ["T4"]
    assert args.max_dauer == 330
    assert args.sortierung == "distance_km"
    assert args.absteigend is True
    assert args.limit == 3


def test_parser_rejects_an_unknown_sort_column() -> None:
    """Die Weissliste der Ablage gilt schon beim Einlesen der Argumente."""
    with pytest.raises(SystemExit):
        query.build_parser().parse_args(["--sortierung", "gibtesnicht"])


def test_parser_accepts_several_difficulties_at_once() -> None:
    args = query.build_parser().parse_args(["--schwierigkeit", "T4", "T5"])

    assert args.schwierigkeit == ["T4", "T5"]


def test_repeated_difficulty_option_adds_instead_of_overwriting() -> None:
    """
    Mit dem ueblichen store haette das zweite --schwierigkeit das erste
    ohne Warnung ersetzt, gesucht worden waere nur nach T5.
    """
    args = query.build_parser().parse_args(
        ["--schwierigkeit", "T4", "--schwierigkeit", "T5"]
    )

    assert args.schwierigkeit == ["T4", "T5"]


def test_both_spellings_can_be_mixed() -> None:
    args = query.build_parser().parse_args(
        ["--schwierigkeit", "T4", "T5", "--region", "Uri", "--schwierigkeit", "ZS"]
    )

    assert args.schwierigkeit == ["T4", "T5", "ZS"]
    assert args.region == "Uri"


def test_difficulty_option_needs_at_least_one_value() -> None:
    with pytest.raises(SystemExit):
        query.build_parser().parse_args(["--schwierigkeit"])


# --- Zusammenspiel ------------------------------------------------------


def test_search_passes_the_filters_through(filled_database: Path) -> None:
    args = query.build_parser().parse_args(["--region", "Italien"])

    with TourStore(filled_database) as store:
        found = query.search(store, args)

    assert [entry["title"] for entry in found] == ["Meraner Hoehenweg"]


def test_search_without_filters_returns_everything(filled_database: Path) -> None:
    args = query.build_parser().parse_args([])

    with TourStore(filled_database) as store:
        assert len(query.search(store, args)) == 2


def test_search_sorts_descending(filled_database: Path) -> None:
    args = query.build_parser().parse_args(
        ["--sortierung", "distance_km", "--absteigend"]
    )

    with TourStore(filled_database) as store:
        found = query.search(store, args)

    assert [entry["distance_km"] for entry in found] == [92.98, 24.17]


def test_main_prints_a_table_and_returns_zero(
    filled_database: Path, capsys
) -> None:
    code = query.main(["--datenbank", str(filled_database), "--region", "Schweiz"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Ronengrat und Klettergarten Gummen" in output
    assert "1 Tour gefunden." in output


def test_main_reports_a_missing_database(tmp_path: Path, capsys) -> None:
    """Ein fehlender Pfad soll eine Ansage geben, keinen Stapelabzug."""
    code = query.main(["--datenbank", str(tmp_path / "gibtesnicht.sqlite3")])

    error = capsys.readouterr().err
    assert code == 1
    assert "Keine Ablage" in error
    assert "main.py" in error


def test_main_uses_the_default_path_when_none_is_given() -> None:
    """
    Ohne --datenbank zeigt das Interface auf die echte Ablage. Der Test
    prueft nur den Standardwert, er oeffnet die Datei nicht.
    """
    args = query.build_parser().parse_args([])

    assert args.datenbank.endswith("tours.sqlite3")


def test_search_with_several_difficulties(filled_database: Path) -> None:
    args = query.build_parser().parse_args(["--schwierigkeit", "T2", "T4"])

    with TourStore(filled_database) as store:
        found = query.search(store, args)

    assert {entry["title"] for entry in found} == {
        "Ronengrat und Klettergarten Gummen",
        "Meraner Hoehenweg",
    }


def test_main_with_repeated_difficulty_option(filled_database: Path, capsys) -> None:
    code = query.main(
        [
            "--datenbank", str(filled_database),
            "--schwierigkeit", "T2",
            "--schwierigkeit", "T4",
        ]
    )

    assert code == 0
    assert "2 Touren gefunden." in capsys.readouterr().out
