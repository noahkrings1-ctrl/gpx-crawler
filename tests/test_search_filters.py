import argparse
from pathlib import Path

import pytest

import query
from storage import TourStore


def tour(**overrides) -> dict:
    metadata = {
        "source_url": "https://www.hikr.org/tour/post1.html",
        "title": "Testtour",
        "date_iso": "2025-02-01",
        "sport": "Wandern",
    }
    metadata.update(overrides)
    return metadata


@pytest.fixture
def database(tmp_path: Path) -> Path:
    target = tmp_path / "tours.sqlite3"
    with TourStore(target) as store:
        store.upsert_tour(
            tour(
                source_url="https://www.hikr.org/tour/post1.html",
                title="Skitour am Oberalp",
                date_iso="2021-03-14",
                sport="Skitour",
                difficulty_ski="WS+",
                main_text="Aufstieg zur Huette, dann eine Nacht im Biwak.",
            )
        )
        store.upsert_tour(
            tour(
                source_url="https://www.hikr.org/tour/post2.html",
                title="Wanderung im Tal",
                date_iso="2025-07-01",
                difficulty_hiking="T2",
                main_text="Kein Stichwort.",
            )
        )
        store.upsert_tour(
            tour(
                source_url="https://www.hikr.org/tour/post3.html",
                title="Alte Tour ohne Datum",
                date_iso=None,
            )
        )
    return target


# --- Datumsgrenzen --------------------------------------------------------


def test_a_year_means_the_whole_year() -> None:
    assert query.parse_date_from("2020") == "2020-01-01"
    assert query.parse_date_to("2020") == "2020-12-31"


def test_full_dates_are_taken_as_they_are() -> None:
    assert query.parse_date_from("2025-06-01") == "2025-06-01"
    assert query.parse_date_to(" 2025-09-30 ") == "2025-09-30"


@pytest.mark.parametrize("value", ["gestern", "2025-13-01", "25"])
def test_nonsense_dates_are_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="kein Jahr"):
        query.parse_date_from(value)


def test_parser_reads_date_range_and_text() -> None:
    args = query.build_parser().parse_args(["--von", "2020", "--bis", "2025", "--text", "biwak"])

    assert args.von == "2020-01-01"
    assert args.bis == "2025-12-31"
    assert args.text == "biwak"


def test_von_after_bis_is_rejected(database: Path) -> None:
    with pytest.raises(SystemExit):
        query.main(["--datenbank", str(database), "--von", "2026", "--bis", "2020"])


# --- Suche ----------------------------------------------------------------


def test_date_range_search(database: Path, capsys) -> None:
    code = query.main(["--datenbank", str(database), "--von", "2021", "--bis", "2021"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Skitour am Oberalp" in output
    assert "Alte Tour ohne Datum" not in output
    assert "1 Tour gefunden." in output


def test_text_search_ignores_the_umlaut_spelling(database: Path, capsys) -> None:
    code = query.main(["--datenbank", str(database), "--text", "Hütte"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Skitour am Oberalp" in output
    assert "1 Tour gefunden." in output


def test_text_search_also_matches_titles(database: Path, capsys) -> None:
    query.main(["--datenbank", str(database), "--text", "wanderung"])

    assert "Wanderung im Tal" in capsys.readouterr().out


def test_skitour_as_sport(database: Path, capsys) -> None:
    query.main(["--datenbank", str(database), "--sportart", "Skitour"])

    output = capsys.readouterr().out
    assert "Skitour am Oberalp" in output
    assert "WS+" in output


def test_ski_scale_is_shown_before_the_others() -> None:
    row = {"difficulty_ski": "WS+", "difficulty_alpine": "ZS", "difficulty_hiking": "T2"}

    assert query.format_difficulty(row) == "WS+"
