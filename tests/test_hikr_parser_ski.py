from pathlib import Path

from parsers.hikr_parser import HikrParser


SKI_HTML = """
<html><body>
  <h1 class="title">Testskitour</h1>
  <table class="fiche_rando">
    <tr><td class="fiche_rando_b">Tour Datum:</td><td class="fiche_rando">8 März 2026</td></tr>
    <tr><td class="fiche_rando_b">Wandern Schwierigkeit:</td><td class="fiche_rando">T2</td></tr>
    <tr><td class="fiche_rando_b">Hochtouren Schwierigkeit:</td><td class="fiche_rando">WS</td></tr>
    <tr><td class="fiche_rando_b">Ski Schwierigkeit:</td><td class="fiche_rando">ZS+</td></tr>
  </table>
  <div id="main_text" class="main_text">
    <div class="markdown">
      <p>Aufstieg   ueber den Gletscher.</p>
      <p>Nacht im Biwak.</p>
    </div>
  </div>
  <div class="content-center">Biwak in der Seitenleiste</div>
</body></html>
"""


def parse(tmp_path: Path, html: str) -> dict:
    path = tmp_path / "tour.html"
    path.write_text(html, encoding="utf-8")
    return HikrParser().parse_local_html(path)


def test_ski_scale_is_read_and_makes_the_tour_a_skitour(tmp_path: Path) -> None:
    result = parse(tmp_path, SKI_HTML)

    assert result["difficulty_ski"] == "ZS+"
    assert result["difficulty_alpine"] == "WS"
    assert result["sport"] == "Skitour"
    assert result["date_iso"] == "2026-03-08"


def test_alternative_ski_label_is_understood(tmp_path: Path) -> None:
    result = parse(tmp_path, SKI_HTML.replace("Ski Schwierigkeit:", "Skitouren Schwierigkeit:"))

    assert result["difficulty_ski"] == "ZS+"


def test_ski_ranks_before_every_other_scale() -> None:
    """Eine Hochtouren oder Wandernote neben der Ski Skala beschreibt nur den Aufstieg."""
    parser = HikrParser()

    assert parser._derive_sport({"difficulty_ski": "WS", "difficulty_alpine": "ZS"}) == "Skitour"
    assert parser._derive_sport({"difficulty_ski": "L", "difficulty_climbing": "VI"}) == "Skitour"
    assert parser._derive_sport({"difficulty_alpine": "ZS", "difficulty_hiking": "T4"}) == "Hochtour"


def test_report_text_comes_only_from_the_report_block(tmp_path: Path) -> None:
    text = parse(tmp_path, SKI_HTML)["main_text"]

    assert "Nacht im Biwak." in text
    assert "Aufstieg ueber den Gletscher." in text
    assert "Seitenleiste" not in text


def test_report_text_is_none_without_report_block(tmp_path: Path) -> None:
    html = SKI_HTML.split('<div id="main_text"')[0] + "</body></html>"

    assert parse(tmp_path, html)["main_text"] is None
