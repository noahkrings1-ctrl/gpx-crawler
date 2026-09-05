from pathlib import Path
from typing import Optional

import gpxpy
import gpxpy.gpx


class GpxParseError(Exception):
    """Raised when a GPX file cannot be read."""


class GpxParser:
    """
    Liest lokale GPX Dateien und berechnet daraus Kennzahlen zur Tour.
    Die Distanz steht bei Hikr nicht im HTML, sie kommt ausschliesslich
    aus der GPX Datei.
    """

    def parse_local_gpx(self, gpx_path: str | Path) -> dict:
        """Read a GPX file from disk and return the calculated values."""
        gpx = self._load(gpx_path)
        return {
            "distance_km": self._distance_km(gpx),
            "point_count": self._count_points(gpx),
        }

    def _load(self, gpx_path: str | Path) -> gpxpy.gpx.GPX:
        """
        Laedt die Datei als Bytes, nicht als Text. Damit bleibt die
        Encoding Deklaration im XML Kopf massgeblich, auch wenn eine Datei
        nicht in UTF-8 vorliegt.
        """
        gpx_path = Path(gpx_path)
        raw = gpx_path.read_bytes()

        try:
            return gpxpy.parse(raw)
        except gpxpy.gpx.GPXException as exc:
            raise GpxParseError(f"Cannot parse GPX file {gpx_path}: {exc}") from exc

    def _distance_km(self, gpx: gpxpy.gpx.GPX) -> Optional[float]:
        """
        Horizontale Streckenlaenge in Kilometern, auf zwei Stellen gerundet.
        Bewusst 2D, weil die Portale die Distanz ebenfalls flach ausweisen und
        die Hoehenmeter separat als Aufstieg und Abstieg gefuehrt werden.
        """
        meters = gpx.length_2d() or 0.0

        # Manche Dateien enthalten statt eines Tracks nur eine geplante Route.
        if not meters:
            meters = sum(route.length() for route in gpx.routes)

        if not meters:
            return None  # Keine verwertbaren Punkte, 0.0 waere irrefuehrend

        return round(meters / 1000.0, 2)

    def _count_points(self, gpx: gpxpy.gpx.GPX) -> int:
        """Zaehlt Track- und Routenpunkte. Erklaert eine Distanz von None."""
        track_points = sum(
            len(segment.points) for track in gpx.tracks for segment in track.segments
        )
        route_points = sum(len(route.points) for route in gpx.routes)
        return track_points + route_points
