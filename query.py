import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Sequence

from storage import TourStore, TourStoreError
from storage.tour_store import DEFAULT_DB_PATH, SORTABLE_COLUMNS


# Ueberschrift, Breite und der Wert je Spalte der Ausgabetabelle.
# Die Breite ist ein Mindestwert, lange Eintraege duerfen sie sprengen.
COLUMNS = (
    ("Datum", 10),
    ("Sportart", 9),
    ("Region", 18),
    ("Schwierigkeit", 22),
    ("Aufstieg", 8),
    ("Dauer", 7),
    ("Distanz", 9),
    ("Titel", 34),
)


def parse_duration(value: str) -> int:
    """
    Nimmt eine Dauer als "5:30" oder als reine Minutenzahl entgegen.

    Beide Schreibweisen sind auf der Kommandozeile naheliegend, und Hikr
    selbst schreibt 5:00. Ohne diese Umrechnung muesste man im Kopf
    multiplizieren.
    """
    text = value.strip()

    match = re.fullmatch(r"(\d{1,3}):(\d{2})", text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))

    if text.isdigit():
        return int(text)

    raise argparse.ArgumentTypeError(
        f"{value!r} ist keine Dauer. Erlaubt sind Minuten wie 330 oder Stunden wie 5:30"
    )


def format_duration(tour: dict) -> str:
    """
    Gehzeit als 5:30, mehrtaegige Touren als Anzahl Tage.

    Die beiden Felder schliessen sich aus, Hikr fuehrt entweder eine
    Gehzeit oder eine Anzahl Tage.
    """
    minutes = tour.get("time_required_min")
    if minutes is not None:
        return f"{minutes // 60}:{minutes % 60:02d}"

    days = tour.get("duration_days")
    if days is not None:
        return f"{days} Tage"

    return "-"


def format_region(tour: dict) -> str:
    """Die aussagekraeftigste Stufe, die vorhanden ist."""
    return tour.get("region_main") or tour.get("region_country") or "-"


def format_difficulty(tour: dict) -> str:
    """
    Die Hochtouren Skala zuerst, danach Wandern, danach Klettern.
    Dieselbe Rangfolge wie bei der Ableitung der Sportart im Parser.
    """
    return (
        tour.get("difficulty_alpine")
        or tour.get("difficulty_hiking")
        or tour.get("difficulty_climbing")
        or "-"
    )


def tour_row(tour: dict) -> list[str]:
    """Eine Tour als Liste von Zellen, in der Reihenfolge von COLUMNS."""
    distance = tour.get("distance_km")
    elevation = tour.get("elevation_gain_m")

    return [
        tour.get("date_iso") or "-",
        tour.get("sport") or "-",
        format_region(tour),
        format_difficulty(tour),
        f"{elevation} m" if elevation is not None else "-",
        format_duration(tour),
        f"{distance:.2f} km" if distance is not None else "-",
        tour.get("title") or "-",
    ]


def format_table(tours: list[dict]) -> str:
    """
    Baut die Tabelle als Zeichenkette, damit sie sich ohne Umleitung der
    Ausgabe testen laesst.

    Die Spalten wachsen mit dem laengsten Eintrag, damit nichts
    abgeschnitten wird. Nur die letzte Spalte bleibt ungepolstert, sonst
    haengen bei kurzen Titeln Leerzeichen am Zeilenende.
    """
    if not tours:
        return "Keine Tour gefunden."

    rows = [tour_row(tour) for tour in tours]
    headers = [name for name, _ in COLUMNS]
    widths = [
        max(minimum, len(header), *(len(row[index]) for row in rows))
        for index, (header, minimum) in enumerate(COLUMNS)
    ]

    def line(cells: Sequence[str]) -> str:
        padded = [
            cell.ljust(widths[index]) if index < len(cells) - 1 else cell
            for index, cell in enumerate(cells)
        ]
        return "  ".join(padded).rstrip()

    output = [line(headers), "-" * min(len(line(headers)), 110)]
    output.extend(line(row) for row in rows)
    output.append("")
    output.append(f"{len(tours)} Tour gefunden." if len(tours) == 1
                  else f"{len(tours)} Touren gefunden.")
    return "\n".join(output)


def build_parser() -> argparse.ArgumentParser:
    """Alle Filter sind freiwillig, ohne Angabe kommt die ganze Ablage."""
    parser = argparse.ArgumentParser(
        prog="query.py",
        description="Sucht in der lokalen Tourdatenbank.",
        epilog=(
            "Beispiele:\n"
            "  python query.py --region Schweiz --sportart Wandern\n"
            "  python query.py --max-aufstieg 1500 --max-dauer 5:30\n"
            "  python query.py --sortierung distance_km --absteigend --limit 5\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--region",
        help="Land, Hauptregion oder Gebiet. Umlaute duerfen ausgeschrieben werden",
    )
    parser.add_argument("--sportart", help="Wandern, Hochtour oder Klettern")
    parser.add_argument(
        "--schwierigkeit",
        help="Teil einer Bewertung, z.B. T4 oder ZS. Sucht in allen drei Skalen",
    )
    parser.add_argument(
        "--min-aufstieg", type=int, metavar="METER", help="Aufstieg mindestens"
    )
    parser.add_argument(
        "--max-aufstieg", type=int, metavar="METER", help="Aufstieg hoechstens"
    )
    parser.add_argument(
        "--max-dauer",
        type=parse_duration,
        metavar="DAUER",
        help="Gehzeit hoechstens, als 5:30 oder als Minuten. "
        "Mehrtaegige Touren fallen dabei heraus",
    )
    parser.add_argument(
        "--sortierung",
        default="date_iso",
        choices=sorted(SORTABLE_COLUMNS),
        metavar="SPALTE",
        help="Sortierspalte, Standard date_iso. Moeglich: "
        + ", ".join(sorted(SORTABLE_COLUMNS)),
    )
    parser.add_argument(
        "--absteigend", action="store_true", help="Groesste Werte zuerst"
    )
    parser.add_argument("--limit", type=int, metavar="ANZAHL", help="Hoechstens so viele")
    parser.add_argument(
        "--datenbank",
        default=str(DEFAULT_DB_PATH),
        metavar="PFAD",
        help=f"Pfad zur Ablage, Standard {DEFAULT_DB_PATH}",
    )

    return parser


def search(store: TourStore, args: argparse.Namespace) -> list[dict]:
    """Uebersetzt die Argumente in einen Aufruf von find_tours."""
    return store.find_tours(
        region=args.region,
        sport=args.sportart,
        difficulty=args.schwierigkeit,
        min_elevation_gain=args.min_aufstieg,
        max_elevation_gain=args.max_aufstieg,
        max_duration_minutes=args.max_dauer,
        order_by=args.sortierung,
        descending=args.absteigend,
        limit=args.limit,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Liefert den Rueckgabewert des Programms, 0 bei Erfolg."""
    # Die Windows Konsole laeuft oft mit cp1252. Ein Titel mit einem Zeichen
    # ausserhalb dieser Tabelle wuerde die Ausgabe sonst mit einem
    # UnicodeEncodeError abbrechen.
    sys.stdout.reconfigure(errors="replace")

    args = build_parser().parse_args(argv)

    if not Path(args.datenbank).exists():
        print(
            f"Keine Ablage unter {args.datenbank}. "
            f"Zuerst python main.py laufen lassen.",
            file=sys.stderr,
        )
        return 1

    try:
        with TourStore(args.datenbank) as store:
            print(format_table(search(store, args)))
    except TourStoreError as exc:
        print(f"Suche fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
