import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


DEFAULT_DB_PATH = Path("data/tours.sqlite3")

# Status einer bekannten URL. neu heisst gefunden, aber noch nicht geladen.
STATUS_NEW = "neu"
STATUS_STORED = "gespeichert"
STATUS_FAILED = "fehlgeschlagen"
URL_STATUSES = frozenset({STATUS_NEW, STATUS_STORED, STATUS_FAILED})

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
    "difficulty_ski": "difficulty_ski",
    "elevation_gain_m": "elevation_gain_m",
    "elevation_loss_m": "elevation_loss_m",
    "time_required": "time_required",
    "time_required_min": "time_required_min",
    "duration_days": "duration_days",
    "distance_km": "distance",
    "language": "language",
    "gpx_url": "gpx_url",
    "gpx_path": "gpx_path",
    "main_text": "main_text",
}

# Spalten, gegen die ein Regionsfilter prueft. Damit trifft "Uri" die
# Hauptregion und "Schweiz" das Land, ohne dass der Aufrufer die Stufe kennt.
REGION_COLUMNS = ("region_country", "region_main", "region_area", "region_leaf")

# Hikr fuehrt je Sportart eine eigene Skala, ein Filter prueft alle vier.
DIFFICULTY_COLUMNS = (
    "difficulty_hiking",
    "difficulty_alpine",
    "difficulty_climbing",
    "difficulty_ski",
)

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
    difficulty_ski      TEXT,
    elevation_gain_m    INTEGER,
    elevation_loss_m    INTEGER,
    time_required       TEXT,
    time_required_min   INTEGER,
    duration_days       INTEGER,
    distance_km         REAL,
    language            TEXT,
    gpx_url             TEXT,
    gpx_path            TEXT,
    main_text           TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tours_date_iso ON tours (date_iso);
CREATE INDEX IF NOT EXISTS idx_tours_sport ON tours (sport);
CREATE INDEX IF NOT EXISTS idx_tours_region_country ON tours (region_country);
CREATE INDEX IF NOT EXISTS idx_tours_region_main ON tours (region_main);
CREATE INDEX IF NOT EXISTS idx_tours_region_leaf ON tours (region_leaf);
CREATE INDEX IF NOT EXISTS idx_tours_elevation_gain ON tours (elevation_gain_m);

CREATE TABLE IF NOT EXISTS discovered_urls (
    url                 TEXT PRIMARY KEY,
    region_id           INTEGER,
    category            TEXT,
    tour_date           TEXT,
    status              TEXT NOT NULL
                        CHECK (status IN ('neu', 'gespeichert', 'fehlgeschlagen')),
    first_seen          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_discovered_search
    ON discovered_urls (region_id, category, status, tour_date);

CREATE TABLE IF NOT EXISTS discovery_progress (
    region_id           INTEGER NOT NULL,
    category            TEXT NOT NULL,
    date_from           TEXT NOT NULL,
    date_to             TEXT NOT NULL,
    resume_skip         INTEGER NOT NULL,
    completed           INTEGER NOT NULL,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (region_id, category, date_from, date_to)
);
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
    Klein. "Österreich" trifft damit "oesterreich" nicht, und auf einer
    deutschsprachigen Seite traegt fast jede Region einen Umlaut. Hier
    werden beide Seiten klein geschrieben und die Umlaute ausgeschrieben,
    danach findet "Österreich", "Oesterreich" und "oesterreich" dasselbe.
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

    Neben den Touren fuehrt die Ablage jede bekannte URL mit Status
    (discovered_urls) und den Fortschritt jeder Discovery Suche
    (discovery_progress). Damit wird keine URL zweimal gecrawlt.

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
        """Legt Tabellen und Indizes an, falls sie noch fehlen."""
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
        now = self._now()

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
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        text: Optional[str] = None,
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

        date_from und date_to sind ISO Daten und schliessen die Grenzen ein.
        Touren ohne Datum fallen bei einem Datumsfilter heraus.

        text sucht als Teilzeichenkette im Berichtstext und im Titel, nach
        derselben Normalisierung wie die uebrigen Filter.

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
            # Je Begriff alle Skalen mit oder, die Begriffe untereinander
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

        if date_from:
            conditions.append("date_iso >= ?")
            parameters.append(date_from)

        if date_to:
            conditions.append("date_iso <= ?")
            parameters.append(date_to)

        text_term = normalise(text)
        if text_term:
            conditions.append("(normalise(main_text) LIKE ? OR normalise(title) LIKE ?)")
            parameters.extend([f"%{text_term}%"] * 2)

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

    # --- Bekannte URLs und Discovery Fortschritt ---------------------------

    def is_known_url(self, url: str) -> bool:
        """
        Bekannt ist eine URL, sobald sie gespeichert oder gefunden wurde,
        unabhaengig vom Status. Die Discovery liefert nur unbekannte URLs,
        dadurch wird nichts doppelt gecrawlt.
        """
        try:
            row = (
                self._require_connection()
                .execute(
                    "SELECT EXISTS (SELECT 1 FROM tours WHERE source_url = ?) "
                    "OR EXISTS (SELECT 1 FROM discovered_urls WHERE url = ?)",
                    (url, url),
                )
                .fetchone()
            )
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann {url} nicht pruefen: {exc}") from exc
        return bool(row[0])

    def url_status(self, url: str) -> Optional[str]:
        """Status einer bekannten URL, sonst None."""
        try:
            row = (
                self._require_connection()
                .execute("SELECT status FROM discovered_urls WHERE url = ?", (url,))
                .fetchone()
            )
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann den Status von {url} nicht lesen: {exc}") from exc
        return row["status"] if row else None

    def skip_reason(self, url: str) -> Optional[str]:
        """
        Grund, eine URL nicht zu laden, sonst None. Gespeicherte Touren und
        dauerhaft fehlgeschlagene URLs werden nie erneut angefragt.
        """
        if self.get_by_url(url) is not None:
            return "bereits gespeichert"
        if self.url_status(url) == STATUS_FAILED:
            return "frueher dauerhaft fehlgeschlagen"
        return None

    def add_discovered(
        self,
        entries: Iterable[tuple[str, Optional[str]]],
        region_id: int,
        category: str,
    ) -> int:
        """
        Legt gefundene URLs mit Tourdatum und Status neu ab und liefert, wie
        viele davon wirklich neu waren. Die URL ist Primaerschluessel, ein
        Duplikat laesst die Datenbank schlicht nicht zu.
        """
        now = self._now()
        rows = [
            (url, region_id, category, tour_date, STATUS_NEW, now, now)
            for url, tour_date in entries
        ]
        connection = self._require_connection()
        try:
            before = connection.total_changes
            connection.executemany(
                "INSERT OR IGNORE INTO discovered_urls "
                "(url, region_id, category, tour_date, status, first_seen, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann gefundene URLs nicht ablegen: {exc}") from exc
        return connection.total_changes - before

    def record_url_status(self, url: str, status: str) -> None:
        """
        Haelt fest, wie ein Ladeversuch ausging. Auch URLs aus der festen
        Liste landen hier, damit fuer beide Modi dieselben Regeln gelten.
        """
        if status not in URL_STATUSES:
            raise TourStoreError(
                f"Unbekannter Status {status!r}, erlaubt sind "
                f"{', '.join(sorted(URL_STATUSES))}"
            )
        now = self._now()
        connection = self._require_connection()
        try:
            connection.execute(
                "INSERT INTO discovered_urls (url, status, first_seen, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET status = excluded.status, "
                "updated_at = excluded.updated_at",
                (url, status, now, now),
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann den Status von {url} nicht ablegen: {exc}") from exc

    def pending_urls(
        self,
        region_id: int,
        category: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[str]:
        """
        Gefundene, aber noch nicht geladene URLs einer Suche, neueste Tour
        zuerst. Mit Datumsbereich zaehlen nur URLs mit bekanntem Tourdatum.
        """
        conditions = ["status = ?", "region_id = ?", "category = ?"]
        parameters: list[Any] = [STATUS_NEW, region_id, category]
        if date_from:
            conditions.append("tour_date >= ?")
            parameters.append(date_from)
        if date_to:
            conditions.append("tour_date <= ?")
            parameters.append(date_to)

        query = (
            "SELECT url FROM discovered_urls WHERE "
            + " AND ".join(conditions)
            + " ORDER BY tour_date IS NULL, tour_date DESC, url"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        try:
            rows = self._require_connection().execute(query, parameters).fetchall()
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann offene URLs nicht lesen: {exc}") from exc
        return [row["url"] for row in rows]

    def get_progress(
        self,
        region_id: int,
        category: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Optional[dict]:
        """Stand einer Discovery Suche, sonst None."""
        try:
            row = (
                self._require_connection()
                .execute(
                    "SELECT resume_skip, completed, updated_at FROM discovery_progress "
                    "WHERE region_id = ? AND category = ? AND date_from = ? AND date_to = ?",
                    (region_id, category, date_from or "", date_to or ""),
                )
                .fetchone()
            )
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann den Suchstand nicht lesen: {exc}") from exc
        if row is None:
            return None
        return {
            "resume_skip": int(row["resume_skip"]),
            "completed": bool(row["completed"]),
            "updated_at": row["updated_at"],
        }

    def save_progress(
        self,
        region_id: int,
        category: str,
        date_from: Optional[str],
        date_to: Optional[str],
        resume_skip: int,
        completed: bool,
    ) -> None:
        """
        Merkt sich, wie weit eine Suche gekommen ist. Eine einmal vollstaendig
        durchsuchte Suche bleibt vollstaendig, auch wenn ein spaeterer Lauf
        nur die neuesten Seiten nach neuen Berichten absucht.
        """
        connection = self._require_connection()
        try:
            connection.execute(
                "INSERT INTO discovery_progress "
                "(region_id, category, date_from, date_to, resume_skip, completed, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(region_id, category, date_from, date_to) DO UPDATE SET "
                "resume_skip = excluded.resume_skip, "
                "completed = MAX(discovery_progress.completed, excluded.completed), "
                "updated_at = excluded.updated_at",
                (
                    region_id,
                    category,
                    date_from or "",
                    date_to or "",
                    resume_skip,
                    int(bool(completed)),
                    self._now(),
                ),
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise TourStoreError(f"Kann den Suchstand nicht ablegen: {exc}") from exc

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise TourStoreError("Keine Verbindung, bitte zuerst connect aufrufen")
        return self.connection
