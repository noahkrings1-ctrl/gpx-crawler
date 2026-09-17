from pathlib import Path

import gpxpy
import pytest

from parsers.gpx_parser import GpxParseError, GpxParser


HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
GPX_OPEN = '<gpx version="1.1" creator="hikr.org" xmlns="http://www.topografix.com/GPX/1/1">'

# 0.01 Grad Breite entsprechen rund 1.11 km. Damit ist die erwartete
# Distanz von Hand nachrechenbar und haengt nicht an gpxpy selbst.
TRACK_GPX = f"""{HEADER}
{GPX_OPEN}
  <trk><name>Sunnig Wichel</name><trkseg>
    <trkpt lat="46.80" lon="8.60"><ele>1200</ele></trkpt>
    <trkpt lat="46.81" lon="8.60"><ele>1600</ele></trkpt>
  </trkseg></trk>
</gpx>
"""

TWO_SEGMENTS_GPX = f"""{HEADER}
{GPX_OPEN}
  <trk><trkseg>
    <trkpt lat="46.80" lon="8.60"></trkpt>
    <trkpt lat="46.81" lon="8.60"></trkpt>
  </trkseg>
  <trkseg>
    <trkpt lat="46.90" lon="8.60"></trkpt>
    <trkpt lat="46.91" lon="8.60"></trkpt>
  </trkseg></trk>
</gpx>
"""

ROUTE_GPX = f"""{HEADER}
{GPX_OPEN}
  <rte>
    <rtept lat="46.80" lon="8.60"></rtept>
    <rtept lat="46.81" lon="8.60"></rtept>
  </rte>
</gpx>
"""

EMPTY_GPX = f"""{HEADER}
{GPX_OPEN}
  <trk><name>Ohne Punkte</name><trkseg></trkseg></trk>
</gpx>
"""


def write_gpx(tmp_path: Path, content: str, name: str = "tour.gpx") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_distance_from_single_track(tmp_path: Path) -> None:
    result = GpxParser().parse_local_gpx(write_gpx(tmp_path, TRACK_GPX))

    assert result["distance_km"] == pytest.approx(1.11, abs=0.01)
    assert result["point_count"] == 2


def test_distance_sums_all_segments(tmp_path: Path) -> None:
    """Zwei getrennte Segmente werden addiert, die Luecke dazwischen nicht."""
    result = GpxParser().parse_local_gpx(write_gpx(tmp_path, TWO_SEGMENTS_GPX))

    assert result["distance_km"] == pytest.approx(2.23, abs=0.02)
    assert result["point_count"] == 4


def test_distance_from_route_only_file(tmp_path: Path) -> None:
    """Dateien ohne Track, aber mit geplanter Route, duerfen nicht 0 ergeben."""
    result = GpxParser().parse_local_gpx(write_gpx(tmp_path, ROUTE_GPX))

    assert result["distance_km"] == pytest.approx(1.11, abs=0.01)
    assert result["point_count"] == 2


def test_distance_is_none_without_points(tmp_path: Path) -> None:
    result = GpxParser().parse_local_gpx(write_gpx(tmp_path, EMPTY_GPX))

    assert result["distance_km"] is None
    assert result["point_count"] == 0


def test_broken_xml_raises_gpx_parse_error(tmp_path: Path) -> None:
    path = write_gpx(tmp_path, "<gpx>abgeschnitten")

    with pytest.raises(GpxParseError, match="Cannot parse GPX file"):
        GpxParser().parse_local_gpx(path)


def test_latin1_encoded_file_is_read_correctly(tmp_path: Path) -> None:
    """Die Encoding Deklaration im XML Kopf muss massgeblich bleiben."""
    content = TRACK_GPX.replace("UTF-8", "ISO-8859-1").replace(
        "Sunnig Wichel", "Piz Palue Ueberschreitung"
    )
    path = tmp_path / "latin1.gpx"
    path.write_bytes(content.encode("iso-8859-1"))

    result = GpxParser().parse_local_gpx(path)

    assert result["distance_km"] == pytest.approx(1.11, abs=0.01)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        GpxParser().parse_local_gpx(tmp_path / "gibtesnicht.gpx")


# --- Fehlerhafte Dateikoepfe ------------------------------------------------

# Nachbau des Dateikopfs aelterer Swisstopo App Versionen: xmlns:schemaLocation
# statt xsi:schemaLocation, mit vier Adressen in einer Namensraum Deklaration.
SWISSTOPO_HEADER = (
    '<gpx version="1.1" creator="Nachbau einer aelteren Swisstopo App Datei" '
    'xmlns="http://www.topografix.com/GPX/1/1" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns:swisstopo="https://prod-static.swisstopo-app.ch/xmlschemas/SwisstopoExtensions" '
    'xmlns:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd '
    'https://swisstopo-app.ch/xmlschemas/SwisstopoExtensions '
    'https://prod-static.swisstopo-app.ch/xmlschemas/SwisstopoExtensions.xsd">'
)

SWISSTOPO_GPX = TRACK_GPX.replace(GPX_OPEN, SWISSTOPO_HEADER)

UNREPAIRABLE_GPX = TRACK_GPX.replace(
    GPX_OPEN,
    '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
    'xmlns:kaputt="eine adresse mit leerzeichen">',
)


def test_misdeclared_schema_location_trips_gpxpy() -> None:
    """Voraussetzung der Reparatur: gpxpy wirft hier einen ValueError aus lxml."""
    assert SWISSTOPO_HEADER in SWISSTOPO_GPX

    with pytest.raises(ValueError, match="Invalid namespace URI"):
        gpxpy.parse(SWISSTOPO_GPX)


def test_swisstopo_file_with_misdeclared_schema_location_is_repaired(tmp_path: Path) -> None:
    path = write_gpx(tmp_path, SWISSTOPO_GPX)
    before = path.read_bytes()

    result = GpxParser().parse_local_gpx(path)

    assert result["distance_km"] == pytest.approx(1.11, abs=0.01)
    assert result["point_count"] == 2
    assert path.read_bytes() == before


def test_any_other_read_error_becomes_gpx_parse_error(tmp_path: Path) -> None:
    """Frueher brach ein ValueError aus lxml den ganzen Lauf ab."""
    assert "xmlns:kaputt" in UNREPAIRABLE_GPX

    with pytest.raises(GpxParseError, match="Cannot parse GPX file"):
        GpxParser().parse_local_gpx(write_gpx(tmp_path, UNREPAIRABLE_GPX))
