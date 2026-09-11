from pathlib import Path

import pytest

from storage import TourStore, TourStoreError
from storage.tour_store import normalise


def sample(**overrides) -> dict:
    """Metadaten, wie sie der Parser und main.py liefern."""
    metadata = {
        "source_url": "https://www.hikr.org/tour/post203736.html",
        "title": "Ortler via neue Olaf Reinstadler-Route",
        "region": "Welt , Italien , Trentino-Suedtirol",
        "region_country": "Italien",
        "region_main": "Trentino-Suedtirol",
        "region_area": None,
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
def store(tmp_path: Path):
    """Eine Ablage je Test, pytest raeumt tmp_path selbst wieder auf."""
    with TourStore(tmp_path / "tours.sqlite3") as opened:
        yield opened


@pytest.fixture
def filled_store():
    """
    Ablage im Arbeitsspeicher mit einer Handvoll Touren. Fuer reine
    Abfragetests, die nichts schreiben muessen, ist das schneller und kann
    prinzipbedingt nichts auf der Platte hinterlassen.
    """
    with TourStore(":memory:") as opened:
        opened.upsert_many(
            [
                sample(),  # Hochtour, Italien, 1700 m, mehrtaegig
                sample(
                    source_url="https://x/uri.html",
                    title="Laeged und Schaechentaler Windgaellen",
                    region_country="Schweiz",
                    region_main="Uri",
                    region_area=None,
                    region_leaf="Uri",
                    date_iso="2026-08-12",
                    sport="Wandern",
                    difficulty_hiking="T5 - anspruchsvolles Alpinwandern",
                    difficulty_alpine=None,
                    difficulty_climbing="II (UIAA-Skala)",
                    elevation_gain_m=1270,
                    time_required_min=330,
                    duration_days=None,
                    distance=13.08,
                ),
                sample(
                    source_url="https://x/engadin.html",
                    title="Von Sils Maria nach Maloja",
                    region_country="Schweiz",
                    region_main="Graubuenden",
                    region_area="Oberengadin",
                    region_leaf="Oberengadin",
                    date_iso="2026-06-03",
                    sport="Wandern",
                    difficulty_hiking="T1 - Wandern",
                    difficulty_alpine=None,
                    difficulty_climbing=None,
                    elevation_gain_m=200,
                    time_required_min=105,
                    duration_days=None,
                    distance=7.09,
                ),
                sample(
                    source_url="https://x/oetztal.html",
                    title="Ueber die Fuorcla",
                    region_country="Oesterreich",
                    region_main="Zentrale Ostalpen",
                    region_area="Oetztaler Alpen",
                    region_leaf="Oetztaler Alpen",
                    date_iso=None,
                    sport="Wandern",
                    difficulty_hiking="T4 - Alpinwandern",
                    difficulty_alpine=None,
                    difficulty_climbing=None,
                    elevation_gain_m=850,
                    time_required_min=255,
                    duration_days=None,
                    distance=None,
                ),
            ]
        )
        yield opened


def titles(tours: list[dict]) -> set[str]:
    return {tour["title"] for tour in tours}


# --- Schema und Ablegen -------------------------------------------------


def test_schema_is_created_on_enter(store) -> None:
    tables = store.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()

    assert "tours" in [row["name"] for row in tables]
    assert store.count() == 0


def test_upsert_stores_all_fields(store) -> None:
    store.upsert_tour(sample())
    stored = store.get_by_url(sample()["source_url"])

    assert stored["title"] == "Ortler via neue Olaf Reinstadler-Route"
    assert stored["sport"] == "Hochtour"
    assert stored["region_country"] == "Italien"
    assert stored["elevation_gain_m"] == 1700
    assert stored["duration_days"] == 2
    assert stored["time_required_min"] is None
    # Im Dictionary heisst das Feld distance, in der Tabelle distance_km.
    assert stored["distance_km"] == pytest.approx(19.06)
    assert stored["created_at"] and stored["updated_at"]


def test_second_run_updates_instead_of_duplicating(store) -> None:
    """Die Quelle URL ist der Schluessel, ein zweiter Lauf legt nichts doppelt an."""
    store.upsert_tour(sample())
    first = store.get_by_url(sample()["source_url"])

    store.upsert_tour(sample(title="Ortler, korrigierter Titel", distance=19.42))

    assert store.count() == 1
    updated = store.get_by_url(sample()["source_url"])
    assert updated["title"] == "Ortler, korrigierter Titel"
    assert updated["distance_km"] == pytest.approx(19.42)
    assert updated["id"] == first["id"]
    # Der Zeitpunkt des ersten Fundes darf nicht verloren gehen.
    assert updated["created_at"] == first["created_at"]


def test_missing_source_url_is_rejected(store) -> None:
    with pytest.raises(TourStoreError, match="source_url"):
        store.upsert_tour(sample(source_url=None))


def test_partial_metadata_is_accepted(store) -> None:
    """Eine Tour ohne Datum, Distanz und Schwierigkeit muss trotzdem hineinpassen."""
    store.upsert_tour({"source_url": "https://www.hikr.org/tour/post1.html"})

    stored = store.get_by_url("https://www.hikr.org/tour/post1.html")
    assert stored["title"] is None
    assert stored["distance_km"] is None
    assert store.count() == 1


def test_all_tours_sorts_by_date_and_puts_undated_last(store) -> None:
    store.upsert_tour(sample(source_url="https://x/2.html", date_iso="2026-08-29"))
    store.upsert_tour(sample(source_url="https://x/1.html", date_iso="2023-06-18"))
    store.upsert_tour(sample(source_url="https://x/3.html", date_iso=None))

    dates = [tour["date_iso"] for tour in store.all_tours()]

    assert dates == ["2023-06-18", "2026-08-29", None]


def test_database_file_is_created_with_missing_folder(tmp_path: Path) -> None:
    target = tmp_path / "noch" / "nicht" / "da" / "tours.sqlite3"

    with TourStore(target) as opened:
        opened.upsert_tour(sample())

    assert target.exists()


def test_data_survives_reopening(tmp_path: Path) -> None:
    target = tmp_path / "tours.sqlite3"
    with TourStore(target) as opened:
        opened.upsert_tour(sample())

    with TourStore(target) as reopened:
        assert reopened.count() == 1
        assert reopened.all_tours()[0]["sport"] == "Hochtour"


def test_use_without_connection_raises(tmp_path: Path) -> None:
    unopened = TourStore(tmp_path / "tours.sqlite3")

    with pytest.raises(TourStoreError, match="Keine Verbindung"):
        unopened.count()


# --- Suche --------------------------------------------------------------


def test_without_any_filter_everything_comes_back(filled_store) -> None:
    assert len(filled_store.find_tours()) == 4


def test_filter_by_country(filled_store) -> None:
    """Schweiz steht in region_country, der Aufrufer muss die Stufe nicht kennen."""
    found = filled_store.find_tours(region="Schweiz")

    assert titles(found) == {
        "Laeged und Schaechentaler Windgaellen",
        "Von Sils Maria nach Maloja",
    }


def test_filter_by_main_region(filled_store) -> None:
    assert titles(filled_store.find_tours(region="Uri")) == {
        "Laeged und Schaechentaler Windgaellen"
    }


def test_filter_by_area(filled_store) -> None:
    assert titles(filled_store.find_tours(region="Oberengadin")) == {
        "Von Sils Maria nach Maloja"
    }


def test_filter_by_sport(filled_store) -> None:
    assert titles(filled_store.find_tours(sport="Hochtour")) == {
        "Ortler via neue Olaf Reinstadler-Route"
    }


def test_filter_by_difficulty_matches_a_partial_grade(filled_store) -> None:
    """T4 muss auch T4 - Alpinwandern treffen, sonst waere der Filter nutzlos."""
    assert titles(filled_store.find_tours(difficulty="T4")) == {
        "Ortler via neue Olaf Reinstadler-Route",
        "Ueber die Fuorcla",
    }


def test_filter_by_difficulty_across_all_three_scales(filled_store) -> None:
    """ZS steht in difficulty_alpine, nicht in difficulty_hiking."""
    assert titles(filled_store.find_tours(difficulty="ZS")) == {
        "Ortler via neue Olaf Reinstadler-Route"
    }


def test_filter_by_elevation_range(filled_store) -> None:
    found = filled_store.find_tours(min_elevation_gain=800, max_elevation_gain=1300)

    assert titles(found) == {
        "Laeged und Schaechentaler Windgaellen",
        "Ueber die Fuorcla",
    }


def test_max_duration_excludes_multi_day_tours(filled_store) -> None:
    """
    Die mehrtaegige Tour hat time_required_min NULL. Ein Vergleich mit NULL
    ist in SQL nie wahr, sie faellt also heraus. Genau richtig, eine
    Zweitagestour ist keine Tour unter sechs Stunden.
    """
    found = filled_store.find_tours(max_duration_minutes=360)

    assert "Ortler via neue Olaf Reinstadler-Route" not in titles(found)
    assert titles(found) == {
        "Laeged und Schaechentaler Windgaellen",
        "Von Sils Maria nach Maloja",
        "Ueber die Fuorcla",
    }


def test_filters_combine_with_and(filled_store) -> None:
    found = filled_store.find_tours(
        region="Schweiz", sport="Wandern", max_elevation_gain=500
    )

    assert titles(found) == {"Von Sils Maria nach Maloja"}


def test_filter_without_match_returns_empty_list(filled_store) -> None:
    assert filled_store.find_tours(region="Groenland") == []


def test_search_terms_are_passed_as_parameters(filled_store) -> None:
    """
    Ein Anführungszeichen im Suchbegriff darf das SQL nicht zerreissen.
    Der Begriff geht als Parameter hinein, nicht per Textformatierung.
    """
    assert filled_store.find_tours(region="'; DROP TABLE tours; --") == []
    # Die Tabelle steht noch.
    assert filled_store.count() == 4


def test_undated_tours_sort_last_in_find(filled_store) -> None:
    dates = [tour["date_iso"] for tour in filled_store.find_tours()]

    assert dates[-1] is None


def test_order_by_and_limit(filled_store) -> None:
    found = filled_store.find_tours(order_by="elevation_gain_m", limit=2)

    assert [tour["elevation_gain_m"] for tour in found] == [200, 850]


def test_unknown_sort_column_is_rejected(filled_store) -> None:
    """Ein Spaltenname landet als Text im SQL, deshalb die Weissliste."""
    with pytest.raises(TourStoreError, match="laesst sich nicht sortieren"):
        filled_store.find_tours(order_by="title; DROP TABLE tours")


def test_in_memory_store_leaves_no_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with TourStore(":memory:") as opened:
        opened.upsert_tour(sample())
        assert opened.count() == 1

    assert list(tmp_path.iterdir()) == []


def test_normalise_writes_out_umlauts() -> None:
    assert normalise("Österreich") == "oesterreich"
    assert normalise("Oesterreich") == "oesterreich"
    assert normalise("Graubünden") == "graubuenden"
    assert normalise("  Zentrale   Ostalpen ") == "zentrale ostalpen"
    assert normalise(None) == ""


def test_region_filter_finds_umlauts_written_either_way(filled_store) -> None:
    """
    SQLite vergleicht bei LIKE nur ASCII. Ohne Normalisierung faende
    "Oesterreich" die Touren in "Oesterreich" nicht, und fast jede Region
    im Alpenraum traegt einen Umlaut.
    """
    filled_store.upsert_tour(
        sample(
            source_url="https://x/umlaut.html",
            title="Tour mit Umlaut",
            region_country="Österreich",
            region_main="Zürichsee",
            region_area=None,
            region_leaf="Zürichsee",
        )
    )

    mit_umlaut = filled_store.find_tours(region="Österreich")
    ausgeschrieben = filled_store.find_tours(region="Oesterreich")
    klein = filled_store.find_tours(region="oesterreich")

    # In der Ablage liegt eine Tour mit echtem Umlaut und eine mit
    # ausgeschriebenem Oe. Jede Schreibweise der Suche muss beide finden.
    assert titles(mit_umlaut) == {"Tour mit Umlaut", "Ueber die Fuorcla"}
    assert titles(ausgeschrieben) == titles(mit_umlaut)
    assert titles(klein) == titles(mit_umlaut)


def test_sport_filter_ignores_case(filled_store) -> None:
    assert titles(filled_store.find_tours(sport="hochtour")) == {
        "Ortler via neue Olaf Reinstadler-Route"
    }


def test_descending_reverses_the_order(filled_store) -> None:
    aufsteigend = filled_store.find_tours(order_by="elevation_gain_m")
    absteigend = filled_store.find_tours(order_by="elevation_gain_m", descending=True)

    hoehen = [tour["elevation_gain_m"] for tour in aufsteigend]
    assert hoehen == sorted(hoehen)
    assert [tour["elevation_gain_m"] for tour in absteigend] == sorted(
        hoehen, reverse=True
    )


def test_empty_fields_stay_last_in_both_directions(filled_store) -> None:
    """
    Eine Tour ohne Datum darf auch beim Umdrehen nicht nach vorne rutschen.
    Leere Felder sind keine besonders kleinen oder grossen Werte, sie
    gehoeren ans Ende.
    """
    assert filled_store.find_tours()[-1]["date_iso"] is None
    assert filled_store.find_tours(descending=True)[-1]["date_iso"] is None


# --- Mehrere Schwierigkeiten --------------------------------------------


def test_filter_by_several_difficulties_finds_each_of_them(filled_store) -> None:
    """Mehrere Begriffe gelten untereinander als oder."""
    assert titles(filled_store.find_tours(difficulty=["T4", "T5"])) == {
        "Ortler via neue Olaf Reinstadler-Route",
        "Ueber die Fuorcla",
        "Laeged und Schaechentaler Windgaellen",
    }


def test_single_difficulty_as_string_or_list_is_the_same(filled_store) -> None:
    """
    Ein String darf nicht Zeichen fuer Zeichen gelesen werden. Sonst
    wuerde aus T5 die Suche nach t oder 5, und t trifft fast alles.
    """
    expected = {"Laeged und Schaechentaler Windgaellen"}

    assert titles(filled_store.find_tours(difficulty="T5")) == expected
    assert titles(filled_store.find_tours(difficulty=["T5"])) == expected


def test_several_difficulties_still_combine_with_other_filters(filled_store) -> None:
    """Untereinander oder, mit den uebrigen Filtern weiterhin und."""
    found = filled_store.find_tours(difficulty=["T4", "T5"], sport="Wandern")

    assert titles(found) == {
        "Ueber die Fuorcla",
        "Laeged und Schaechentaler Windgaellen",
    }


def test_empty_difficulty_list_means_no_filter(filled_store) -> None:
    assert len(filled_store.find_tours(difficulty=[])) == 4
    assert len(filled_store.find_tours(difficulty=["", "  "])) == 4


def test_blank_term_does_not_widen_the_filter(filled_store) -> None:
    """
    Ein leerer Begriff wuerde als LIKE '%%' jede Tour treffen. In einer
    Liste mit oder hebelte er damit den ganzen Filter aus.
    """
    assert titles(filled_store.find_tours(difficulty=["T5", "  "])) == {
        "Laeged und Schaechentaler Windgaellen"
    }


def test_duplicate_difficulties_do_not_change_the_result(filled_store) -> None:
    assert titles(filled_store.find_tours(difficulty=["T5", "t5", "T5"])) == {
        "Laeged und Schaechentaler Windgaellen"
    }
