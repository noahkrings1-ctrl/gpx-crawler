from pathlib import Path

from parsers.hikr_parser import HikrParser


def test_hikr_parser_extracts_metadata(tmp_path: Path) -> None:
    html_content = """
    <html>
      <body>
        <h1>Simple Hikr Tour</h1>
        <div>
          <span>Region:</span> Alpen
        </div>
        <div>
          <span>Date:</span> 2026-05-19
        </div>
        <div>
          <span>Difficulty:</span> T3
        </div>
        <div>
          <span>Distance:</span> 12.5 km
        </div>
        <div>
          <span>Elevation:</span> 950 m
        </div>
        <a href="/download/track.gpx">GPX file</a>
      </body>
    </html>
    """

    html_file = tmp_path / "sample_hikr.html"
    html_file.write_text(html_content, encoding="utf-8")

    parser = HikrParser()
    result = parser.parse_local_html(html_file, base_url="https://www.hikr.org")

    assert result["title"] == "Simple Hikr Tour"
    assert result["region"] == "Alpen"
    assert result["date"] == "2026-05-19"
    assert result["difficulty"] == "T3"
    assert result["distance"] == "12.5 km"
    assert result["elevation_gain"] == "950 m"
    assert result["gpx_url"] == "https://www.hikr.org/download/track.gpx"
