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
