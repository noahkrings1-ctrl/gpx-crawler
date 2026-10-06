"""Die Schneeschuhskala auf der Tourseite."""

from pathlib import Path

from parsers.hikr_parser import HikrParser


# Hikr schreibt die Skala ohne das erste c. Nachgebaut nach einer echten
# Seite, geprueft im Oktober 2026.
SNOWSHOE_HTML = """
<html><body>
  <h1 class="title">Schneeschuhtour Wissmeilen</h1>
  <table class="fiche_rando">
    <tr><td class="fiche_rando_b">Tour Datum:</td><td class="fiche_rando">30 Januar 2026</td></tr>
    <tr><td class="fiche_rando_b">Hochtouren Schwierigkeit:</td><td class="fiche_rando">ZS-</td></tr>
    <tr><td class="fiche_rando_b">Schneeshuhtouren Schwierigkeit:</td>
        <td class="fiche_rando">WT3 - Anspruchsvolle Schneeschuhwanderung</td></tr>
  </table>
  <div id="main_text" class="main_text"><div class="markdown"><p>Mit Schneeschuhen hinauf.</p></div></div>
</body></html>
"""


def parse(tmp_path: Path, html: str) -> dict:
    path = tmp_path / "tour.html"
    path.write_text(html, encoding="utf-8")
    return HikrParser().parse_local_html(path)


def test_the_snowshoe_scale_is_read(tmp_path: Path) -> None:
    result = parse(tmp_path, SNOWSHOE_HTML)

    assert result["difficulty_snowshoe"] == "WT3 - Anspruchsvolle Schneeschuhwanderung"
    assert result["difficulty_alpine"] == "ZS-"
    assert result["date_iso"] == "2026-01-30"


def test_the_correct_spelling_is_understood_too(tmp_path: Path) -> None:
    """Falls Hikr den Tippfehler einmal behebt."""
    richtig = SNOWSHOE_HTML.replace("Schneeshuhtouren", "Schneeschuhtouren")

    assert parse(tmp_path, richtig)["difficulty_snowshoe"].startswith("WT3")


def test_a_tour_with_a_snowshoe_grade_is_a_snowshoe_tour(tmp_path: Path) -> None:
    """
    25 von 30 solchen Touren tragen auch eine Hochtourennote.

    Bisher landeten sie deshalb als Hochtour in der Ablage, obwohl sie im
    Titel Schneeschuhtour heissen.
    """
    assert parse(tmp_path, SNOWSHOE_HTML)["sport"] == "Schneeschuhtour"


def test_snowshoe_ranks_between_ski_and_hochtour() -> None:
    parser = HikrParser()

    assert parser._derive_sport({"difficulty_snowshoe": "WT3"}) == "Schneeschuhtour"
    assert (
        parser._derive_sport({"difficulty_snowshoe": "WT3", "difficulty_alpine": "ZS-"})
        == "Schneeschuhtour"
    )
    assert (
        parser._derive_sport({"difficulty_snowshoe": "WT4", "difficulty_hiking": "T3"})
        == "Schneeschuhtour"
    )
    # Wo eine Skinote steht, ging es mit Ski.
    assert (
        parser._derive_sport({"difficulty_ski": "WS", "difficulty_snowshoe": "WT4"}) == "Skitour"
    )


def test_a_tour_without_the_scale_stays_what_it_was(tmp_path: Path) -> None:
    ohne = SNOWSHOE_HTML.replace("Schneeshuhtouren", "Mountainbike")

    result = parse(tmp_path, ohne)

    assert result["difficulty_snowshoe"] is None
    assert result["sport"] == "Hochtour"


def test_a_line_break_inside_a_value_is_removed(tmp_path: Path) -> None:
    """Hikr bricht die Schneeschuhnote mitten im Wert um, das zerriss die Tabelle."""
    umbrochen = SNOWSHOE_HTML.replace(
        "<td class=\"fiche_rando\">WT3 - Anspruchsvolle Schneeschuhwanderung</td>",
        "<td class=\"fiche_rando\">WT3 - \n Anspruchsvolle Schneeschuhwanderung</td>",
    )

    wert = parse(tmp_path, umbrochen)["difficulty_snowshoe"]

    assert wert == "WT3 - Anspruchsvolle Schneeschuhwanderung"
    assert "\n" not in wert
