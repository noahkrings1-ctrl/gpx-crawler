import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_DB_PATH = Path("data/tours.sqlite3")

# Spalte in der Datenbank -> Schluessel im Metadaten Dictionary.
# Die Distanz heisst im Dictionary distance, in der Tabelle aber distance_km,
# damit die Einheit an der Spalte ablesbar bleibt.
COLUMN_MAP = {
    "source_url": "source_url",
    "title": "title",
    "region": "region",
    "region_leaf": "region_leaf",
    "date": "date",
    "date_iso": "date_iso",
    "sport": "sport",
    "difficulty_hiking": "difficulty_hiking",
    "difficulty_alpine": "difficulty_alpine",
    "difficulty_climbing": "difficulty_climbing",
    "elevation_gain_m": "elevation_gain_m",
    "elevation_loss_m": "elevation_loss_m",
    "time_required": "time_required",
    "time_required_min": "time_required_min",
    "duration_days": "duration_days",
    "distance_km": "distance",
    "language": "language",
    "gpx_url": "gpx_url",
    "gpx_path": "gpx_path",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tours (
    id                 INTEGER PRIMARY KEY,
    source_url         TEXT NOT NULL UNIQUE,
    title              TEXT,
    region             TEXT,
    region_leaf        TEXT,
    date               TEXT,
    date_iso           TEXT,
    sport              TEXT,
    difficulty_hiking  TEXT,
    difficulty_alpine  TEXT,
    difficulty_climbing TEXT,
    elevation_gain_m   INTEGER,
    elevation_loss_m   INTEGER,
    time_required      TEXT,
    time_required_min  INTEGER,
    duration_days      INTEGER,
    distance_km        REAL,
    language           TEXT,
    gpx_url            TEXT,
    gpx_path           TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tours_date_iso ON tours (date_iso);
CREATE INDEX IF NOT EXISTS idx_tours_sport ON tours (sport);
CREATE INDEX IF NOT EXISTS idx_tours_region_leaf ON tours (region_leaf);
"""


class TourDatabase:
    """
    Lokale SQLite Ablage der Tourmetadaten. Eine Datei, kein Server.

    Die Quelle URL ist der Schluessel. Ein zweiter Lauf ueber dieselbe Tour
    aktualisiert den Datensatz, statt ihn ein zweites Mal anzulegen.
    Das gesamte SQL des Projekts steht in diesem Modul, damit ein Wechsel
    auf einen ORM spaeter nur hier stattfinden muesste.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "TourDatabase":
        self.connect()
        self.create_schema()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def connect(self) -> sqlite3.Connection:
        """Oeffnet die Datenbank und legt fehlende Ordner an."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        # Zeilen als Row, damit sich Spalten ueber ihren Namen lesen lassen.
        self.connection.row_factory = sqlite3.Row
        # Fuer die spaeteren Tag Tabellen, SQLite prueft sonst keine Bezuege.
        self.connection.execute("PRAGMA foreign_keys = ON")
        return self.connection

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def create_schema(self) -> None:
        """Legt Tabelle und Indizes an, falls sie noch fehlen."""
        self._require_connection().executescript(SCHEMA)
        self._require_connection().commit()

    def upsert_tour(self, metadata: dict) -> int:
        """
        Schreibt eine Tour und liefert ihre id. Vorhandene Datensaetze werden
        anhand der Quelle URL aktualisiert, created_at bleibt dabei erhalten.
        """
        source_url = metadata.get("source_url")
        if not source_url:
            raise ValueError("Metadaten ohne source_url koennen nicht abgelegt werden")

        columns = list(COLUMN_MAP)
        values = [metadata.get(key) for key in COLUMN_MAP.values()]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        placeholders = ", ".join("?" for _ in columns) + ", ?, ?"
        column_list = ", ".join(columns) + ", created_at, updated_at"
        # created_at steht bewusst nicht im UPDATE, sonst ginge der
        # Zeitpunkt des ersten Fundes bei jedem Lauf verloren.
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns)

        cursor = self._require_connection().execute(
            f"INSERT INTO tours ({column_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(source_url) DO UPDATE SET {updates}, updated_at = excluded.updated_at",
            values + [now, now],
        )
        self._require_connection().commit()

        if cursor.lastrowid:
            return int(cursor.lastrowid)
        return int(self.get_by_url(source_url)["id"])

    def upsert_many(self, tours: Iterable[dict]) -> int:
        """Legt mehrere Touren ab und liefert die Anzahl."""
        return sum(1 for tour in tours if self.upsert_tour(tour))

    def get_by_url(self, source_url: str) -> Optional[dict]:
        row = self._require_connection().execute(
            "SELECT * FROM tours WHERE source_url = ?", (source_url,)
        ).fetchone()
        return dict(row) if row else None

    def all_tours(self) -> list[dict]:
        """Alle Touren, aelteste zuerst. Touren ohne Datum stehen am Ende."""
        rows = self._require_connection().execute(
            "SELECT * FROM tours ORDER BY date_iso IS NULL, date_iso"
        ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        return int(
            self._require_connection().execute("SELECT COUNT(*) FROM tours").fetchone()[0]
        )

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("Keine Verbindung, bitte zuerst connect aufrufen")
        return self.connection
