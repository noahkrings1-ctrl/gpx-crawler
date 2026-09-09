from pathlib import Path

from parsers.hikr_parser import HikrParser


def test_hikr_parser_extracts_metadata(tmp_path: Path) -> None:
    html_content = """
    <html>
      <body>
        <h1 class="title">Sunnig Wichel via Nordgrat</h1>
        <table class="fiche_rando">
          <tr>
            <td class="fiche_rando_b">Region:</td>
            <td class="fiche_rando">
              <a>Welt</a> » <a>Schweiz</a> » <a>Uri</a>
            </td>
          </tr>
          <tr>
            <td class="fiche_rando_b">Tour Datum:</td>
            <td class="fiche_rando">12 Juli 2026</td>
          </tr>
          <tr>
            <td class="fiche_rando_b">Hochtouren Schwierigkeit:</td>
            <td class="fiche_rando">ZS</td>
          </tr>
          <tr>
            <td class="fiche_rando_b">Aufstieg:</td>
            <td class="fiche_rando">2200 m</td>
          </tr>
          <tr>
            <td class="fiche_rando_b">Abstieg:</td>
            <td class="fiche_rando">2200 m</td>
          </tr>
        </table>
        <a href="https://f.hikr.org/files/gps71129.gpx">71129.gpx</a>
      </body>
    </html>
    """

    html_file = tmp_path / "sample_hikr.html"
    html_file.write_text(html_content, encoding="utf-8")

    parser = HikrParser()
    result = parser.parse_local_html(html_file, base_url="https://www.hikr.org")

    assert result["title"] == "Sunnig Wichel via Nordgrat"
    assert "Uri" in result["region"]
    assert result["date"] == "12 Juli 2026"
    assert result["date_iso"] == "2026-07-12"
    assert result["difficulty_alpine"] == "ZS"
    assert result["elevation_gain"] == "2200 m"
    assert result["elevation_loss"] == "2200 m"
    assert result["distance"] is None
    assert result["gpx_url"] == "https://f.hikr.org/files/gps71129.gpx"


def test_hikr_parser_normalises_written_out_dates() -> None:
    parser = HikrParser()

    assert parser._parse_date_iso("12 Juli 2026") == "2026-07-12"
    assert parser._parse_date_iso("1. Maerz 2025") == "2025-03-01"
    assert parser._parse_date_iso("9 März 2025") == "2025-03-09"
    assert parser._parse_date_iso("12.07.2026") == "2026-07-12"


def test_hikr_parser_returns_none_for_unreadable_dates() -> None:
    """Ein unlesbares Datum darf den Lauf nicht abbrechen."""
    parser = HikrParser()

    assert parser._parse_date_iso(None) is None
    assert parser._parse_date_iso("") is None
    assert parser._parse_date_iso("irgendwann im Sommer") is None
    assert parser._parse_date_iso("32 Juli 2026") is None


def test_hikr_parser_converts_elevation_to_meters() -> None:
    parser = HikrParser()

    assert parser._parse_meters("1270 m") == 1270
    assert parser._parse_meters("1'270 m") == 1270
    assert parser._parse_meters("200 m") == 200
    assert parser._parse_meters(None) is None
    assert parser._parse_meters("keine Angabe") is None


def test_hikr_parser_separates_hours_from_multi_day_tours() -> None:
    """
    Hikr fuehrt den Zeitbedarf in zwei Formaten. "6 Tage" in Minuten
    umzurechnen wuerde Gehzeit und Kalendertage vermischen, deshalb
    zwei getrennte Felder.
    """
    parser = HikrParser()

    assert parser._parse_minutes("5:00") == 300
    assert parser._parse_minutes("4:15") == 255
    assert parser._parse_minutes("10:00") == 600
    assert parser._parse_minutes("6 Tage") is None

    assert parser._parse_days("6 Tage") == 6
    assert parser._parse_days("2 Tage") == 2
    assert parser._parse_days("5:00") is None
    assert parser._parse_days(None) is None


def test_hikr_parser_takes_the_most_specific_region() -> None:
    parser = HikrParser()

    assert parser._region_leaf("Welt , Schweiz , Uri") == "Uri"
    assert parser._region_leaf("Welt , Liechtenstein") == "Liechtenstein"
    assert parser._region_leaf(None) is None


def test_hikr_parser_derives_the_sport_from_the_difficulty_scale() -> None:
    """
    Eine UIAA Note neben einer T Note markiert nur eine Kletterstelle.
    Die Tour bleibt eine Wanderung. Nur die Hochtouren Skala schlaegt beides.
    """
    parser = HikrParser()

    assert parser._derive_sport({"difficulty_hiking": "T4 - Alpinwandern"}) == "Wandern"
    assert parser._derive_sport({"difficulty_climbing": "IV (UIAA-Skala)"}) == "Klettern"
    assert parser._derive_sport(
        {"difficulty_hiking": "T5", "difficulty_climbing": "II (UIAA-Skala)"}
    ) == "Wandern"
    assert parser._derive_sport(
        {"difficulty_hiking": "T4", "difficulty_alpine": "ZS-", "difficulty_climbing": "III"}
    ) == "Hochtour"
    assert parser._derive_sport({}) is None


def test_hikr_parser_splits_the_region_into_levels() -> None:
    """
    Die erste Stufe heisst bei Hikr immer Welt und faellt weg. Danach
    folgen Land, Hauptregion und Gebiet, je nach Tour unvollstaendig.
    """
    parser = HikrParser()

    assert parser._split_region("Welt , Schweiz , Graubuenden , Oberengadin") == (
        "Schweiz",
        "Graubuenden",
        "Oberengadin",
    )
    assert parser._split_region("Welt , Schweiz , Uri") == ("Schweiz", "Uri", None)
    assert parser._split_region("Welt , Liechtenstein") == ("Liechtenstein", None, None)
    assert parser._split_region(None) == (None, None, None)
    assert parser._split_region("") == (None, None, None)


def test_hikr_parser_region_levels_work_without_the_world_prefix() -> None:
    """Fehlt die Stufe Welt, darf nichts verrutschen."""
    parser = HikrParser()

    assert parser._split_region("Schweiz , Wallis") == ("Schweiz", "Wallis", None)


def test_hikr_parser_keeps_region_leaf_alongside_the_levels() -> None:
    """
    Die mittlere Stufe ist in der Schweiz der Kanton, in Oesterreich eine
    Gebirgsgruppe. Deshalb der neutrale Name, und region_leaf bleibt
    zusaetzlich als spezifischster Teil erhalten.
    """
    parser = HikrParser()
    chain = "Welt , Oesterreich , Zentrale Ostalpen , Oetztaler Alpen"

    assert parser._split_region(chain) == (
        "Oesterreich",
        "Zentrale Ostalpen",
        "Oetztaler Alpen",
    )
    assert parser._region_leaf(chain) == "Oetztaler Alpen"
