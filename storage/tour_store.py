import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


DEFAULT_DB_PATH = Path("data/tours.sqlite3")

# Spalte in der Datenbank -> Schluessel im Metadaten Dictionary.
# Die Distanz heisst im Dictionary distance, in der Tabelle aber distance_km,
# damit die Einheit an der Spalte ablesbar bleibt.
COLUMN_MAP = {
    "source_url": "source_url",
    "title": "title",
    "region": "region",
    "region_country": "region_country",
    "region_main": "region_main",
    "region_area": "region_area",
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

# Spalten, gegen die ein Regionsfilter prueft. Damit trifft "Uri" die
# Hauptregion und "Schweiz" das Land, ohne dass der Aufrufer die Stufe kennt.
REGION_COLUMNS = ("region_country", "region_main", "region_area", "region_leaf")

# Hikr fuehrt je Sportart eine eigene Skala, ein Filter prueft alle drei.
DIFFICULTY_COLUMNS = ("difficulty_hiking", "difficulty_alpine", "difficulty_climbing")

# Nur diese Spalten duerfen sortieren. Ein Spaltenname laesst sich nicht als
# Platzhalter uebergeben, er landet als Text im SQL. Ohne diese Liste waere
# order_by ein offenes Einfallstor.
SORTABLE_COLUMNS = frozenset(
    {
        "date_iso",
        "title",
        "distance_km",
        "elevation_gain_m",
        "elevation_loss_m",
        "time_required_min",
        "sport",
        "region_country",
        "region_main",
        "region_leaf",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tours (
    id                  INTEGER PRIMARY KEY,
    source_url          TEXT NOT NULL UNIQUE,
    title               TEXT,
    region              TEXT,
    region_country      TEXT,
    region_main         TEXT,
    region_area         TEXT,
    region_leaf         TEXT,
    date                TEXT,
    date_iso            TEXT,
    sport               TEXT,
    difficulty_hiking   TEXT,
    difficulty_alpine   TEXT,
    difficulty_climbing TEXT,
    elevation_gain_m    INTEGER,
    elevation_loss_m    INTEGER,
    time_required       TEXT,
    time_required_min   INTEGER,
    duration_days       INTEGER,
    distance_km         REAL,
    language            TEXT,
    gpx_url             TEXT,
    gpx_path            TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tours_date_iso ON tours (date_iso);
CREATE INDEX IF NOT EXISTS idx_tours_sport ON tours (sport);
CREATE INDEX IF NOT EXISTS idx_tours_region_country ON tours (region_country);
CREATE INDEX IF NOT EXISTS idx_tours_region_main ON tours (region_main);
CREATE INDEX IF NOT EXISTS idx_tours_region_leaf ON tours (region_leaf);
CREATE INDEX IF NOT EXISTS idx_tours_elevation_gain ON tours (elevation_gain_m);
"""


UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
}


def normalise(text: Optional[str]) -> str:
    """
    Macht Suchbegriff und Spaltenwert vergleichbar.

    SQLite vergleicht bei LIKE nur ASCII ohne Ruecksicht auf Gross und
    Klein. "Oesterreich" trifft damit "Oesterreich" nicht, und auf einer
    deutschsprachigen Seite traegt fast jede Region einen Umlaut. Hier
    werden beide Seiten klein geschrieben und die Umlaute ausgeschrieben,
    danach findet "Oesterreich", "Oesterreich" und "oesterreich" dasselbe.
    """
    if not text:
        return ""

    lowered = text.strip().lower()
    for umlaut, replacement in UMLAUT_MAP.items():
        lowered = lowered.replace(umlaut, replacement)

    # Restliche Akzente zerlegen und die Diakritika verwerfen.
    lowered = unicodedata.normalize("NFKD", lowered)
    lowered = lowered.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", lowered).strip()


class TourStoreError(Exception):
    """Raised when the tour store cannot be opened, read or written."""


class TourStore:
    """
    Lokale SQLite Ablage der Tourmetadaten. Eine Datei, kein Server.

    Die Quelle URL ist der Schluessel. Ein zweiter Lauf ueber dieselbe Tour
    aktualisiert den Datensatz, statt ihn ein zweites Mal anzulegen.

    Das gesamte SQL des Projekts steht in diesem Modul, damit ein Wechsel
    auf einen ORM spaeter nur hier stattfaende. Aus demselben Grund verlaesst
    kein sqlite3.Error dieses Modul, alles wird in einen TourStoreError
    eingewickelt. Der Rest des Projekts muss nichts ueber SQLite wissen.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "TourStore":
        self.connect()
        self.create_schema()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def connect(self) -> sqlite3.Connection:
        """Oeffnet die Datenbank und legt fehlende Ordner an."""
        try:
            # ":memory:" ist ein Sonderfall, dafuer gibt es kein Verzeichnis.
            if str(self.db_path) != ":memory:":
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.db_path)
        except (sqlite3.Error, OSError) as exc:
            raise TourStoreError(f"Kann {self.db_path} nicht oeffnen: {exc}") from exc

        # Zeilen als Row, damit sich Spalten ueber ihren Namen lesen lassen.
        self.connection.row_factory = sqlite3.Row
        # Fuer die spaeteren Tag Tabellen, SQLite prueft sonst keine Bezuege.
        self.connection.execute("PRAGMA foreign_keys = ON")
        # Damit sich normalise in einer WHERE Bedingung aufrufen laesst.
        # Ein Index greift dann zwar nicht mehr, bei dieser Datenmenge
        # ist das ohne Belang und ein treffender Filter wiegt schwerer.
        self.connection.create_function("normalise", 1, normalise)
        return self.connection

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def create_schema(self) -> None:
        """Legt Tabelle und Indizes an, falls sie noch fehlen."""
        connection = self._require_connection()
        try:
            connection.executescript(SCHEMA)
            connection.commit()
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann das Schema nicht anlegen: {exc}") from exc

    def upsert_tour(self, metadata: dict) -> int:
        """
        Schreibt eine Tour und liefert ihre id. Vorhandene Datensaetze werden
        anhand der Quelle URL aktualisiert, created_at bleibt dabei erhalten.
        """
        source_url = metadata.get("source_url")
        if not source_url:
            raise TourStoreError(
                "Metadaten ohne source_url koennen nicht abgelegt werden"
            )

        columns = list(COLUMN_MAP)
        values = [metadata.get(key) for key in COLUMN_MAP.values()]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        placeholders = ", ".join("?" for _ in columns) + ", ?, ?"
        column_list = ", ".join(columns) + ", created_at, updated_at"
        # created_at steht bewusst nicht im UPDATE, sonst ginge der
        # Zeitpunkt des ersten Fundes bei jedem Lauf verloren.
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns)

        connection = self._require_connection()
        try:
            cursor = connection.execute(
                f"INSERT INTO tours ({column_list}) VALUES ({placeholders}) "
                f"ON CONFLICT(source_url) DO UPDATE SET {updates}, "
                f"updated_at = excluded.updated_at",
                values + [now, now],
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann {source_url} nicht ablegen: {exc}") from exc

        if cursor.lastrowid:
            return int(cursor.lastrowid)
        return int(self.get_by_url(source_url)["id"])

    def upsert_many(self, tours: Iterable[dict]) -> int:
        """Legt mehrere Touren ab und liefert die Anzahl."""
        return sum(1 for tour in tours if self.upsert_tour(tour))

    @staticmethod
    def _difficulty_terms(difficulty: str | Sequence[str] | None) -> list[str]:
        """
        Macht aus einem Begriff oder einer Liste eine bereinigte Liste.

        Ein String ist in Python selbst eine Folge von Zeichen. Ohne die
        Pruefung vorab wuerde aus "T4" die Suche nach "t" oder "4", und "t"
        steckt in fast jeder Bewertung.

        Leere Begriffe fallen heraus. normalise macht aus ihnen einen leeren
        Text, und LIKE '%%' trifft jede Tour. In einer Liste mit oder wuerde
        ein einziger leerer Begriff den ganzen Filter aushebeln. Doppelte
        Begriffe fallen ebenfalls weg, sie aendern das Ergebnis nicht.
        """
        if difficulty is None:
            return []
        if isinstance(difficulty, str):
            difficulty = [difficulty]
        terms = (normalise(term) for term in difficulty)
        return list(dict.fromkeys(term for term in terms if term))

    def find_tours(
        self,
        region: Optional[str] = None,
        sport: Optional[str] = None,
        difficulty: str | Sequence[str] | None = None,
        min_elevation_gain: Optional[int] = None,
        max_elevation_gain: Optional[int] = None,
        max_duration_minutes: Optional[int] = None,
        order_by: str = "date_iso",
        descending: bool = False,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """
        Sucht Touren. Jeder nicht gesetzte Filter bedeutet keine
        Einschraenkung, ohne jeden Filter kommt die ganze Tabelle zurueck.

        region und difficulty pruefen mehrere Spalten mit OR, damit der
        Aufrufer nicht wissen muss, auf welcher Stufe sein Begriff liegt.
        Beide vergleichen als Teilzeichenkette, "T4" trifft also auch
        "T4 - Alpinwandern" und "Schweiz" trifft ueber das Land.

        difficulty nimmt einen Begriff oder eine Liste. Mehrere Begriffe
        gelten untereinander als oder, T4 und T5 findet also beides. Mit
        den uebrigen Filtern bleibt es bei und.

        max_duration_minutes trifft nur Touren mit gefuellter Gehzeit.
        Mehrtaegige Touren haben dort NULL und fallen heraus, denn ein
        Vergleich mit NULL ist in SQL nie wahr. Das ist so gewollt, eine
        Sechstagestour ist keine Tour unter fuenf Stunden.
        """
        conditions: list[str] = []
        parameters: list[Any] = []

        if region:
            clause = " OR ".join(
                f"normalise({column}) LIKE ?" for column in REGION_COLUMNS
            )
            conditions.append(f"({clause})")
            parameters.extend([f"%{normalise(region)}%"] * len(REGION_COLUMNS))

        if sport:
            conditions.append("normalise(sport) = ?")
            parameters.append(normalise(sport))

        difficulty_terms = self._difficulty_terms(difficulty)
        if difficulty_terms:
            # Je Begriff alle drei Skalen mit oder, die Begriffe untereinander
            # ebenfalls mit oder. Nach aussen bleibt das eine Bedingung, die
            # mit den uebrigen Filtern ueber und verknuepft wird.
            per_term = " OR ".join(
                f"normalise({column}) LIKE ?" for column in DIFFICULTY_COLUMNS
            )
            conditions.append(
                "(" + " OR ".join(f"({per_term})" for _ in difficulty_terms) + ")"
            )
            for term in difficulty_terms:
                parameters.extend([f"%{term}%"] * len(DIFFICULTY_COLUMNS))

        if min_elevation_gain is not None:
            conditions.append("elevation_gain_m >= ?")
            parameters.append(min_elevation_gain)

        if max_elevation_gain is not None:
            conditions.append("elevation_gain_m <= ?")
            parameters.append(max_elevation_gain)

        if max_duration_minutes is not None:
            conditions.append("time_required_min <= ?")
            parameters.append(max_duration_minutes)

        if order_by not in SORTABLE_COLUMNS:
            raise TourStoreError(
                f"Nach {order_by} laesst sich nicht sortieren, erlaubt sind "
                f"{', '.join(sorted(SORTABLE_COLUMNS))}"
            )

        query = "SELECT * FROM tours"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        # Leere Felder ans Ende, sonst stuenden sie in SQLite ganz vorne,
        # und zwar in beiden Sortierrichtungen.
        direction = "DESC" if descending else "ASC"
        query += f" ORDER BY {order_by} IS NULL, {order_by} {direction}"

        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        try:
            rows = self._require_connection().execute(query, parameters).fetchall()
        except sqlite3.Error as exc:
            raise TourStoreError(f"Suche fehlgeschlagen: {exc}") from exc

        return [dict(row) for row in rows]

    def get_by_url(self, source_url: str) -> Optional[dict]:
        """Liefert eine Tour anhand ihrer Quelle URL, sonst None."""
        try:
            row = (
                self._require_connection()
                .execute("SELECT * FROM tours WHERE source_url = ?", (source_url,))
                .fetchone()
            )
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann {source_url} nicht lesen: {exc}") from exc
        return dict(row) if row else None

    def all_tours(self) -> list[dict]:
        """Alle Touren, aelteste zuerst. Touren ohne Datum stehen am Ende."""
        return self.find_tours()

    def count(self) -> int:
        """Anzahl der abgelegten Touren."""
        try:
            return int(
                self._require_connection()
                .execute("SELECT COUNT(*) FROM tours")
                .fetchone()[0]
            )
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann nicht zaehlen: {exc}") from exc

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise TourStoreError("Keine Verbindung, bitte zuerst connect aufrufen")
        return self.connection
