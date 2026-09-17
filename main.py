import argparse
import sys
import time
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlparse

from crawler import Downloader
from crawler.discovery import (
    DEFAULT_MAX_RESULTS,
    MAX_RESULTS_LIMIT,
    PAGE_SIZE,
    DiscoveryError,
    HikrDiscovery,
    date_bounds,
    difficulty_terms,
    resolve_category,
    resolve_region,
    search_key,
    validate_max_results,
    validate_tour_type,
)
from crawler.downloader import (
    CrawlBlockedError,
    DownloadError,
    TransientDownloadError,
    build_polite_downloader,
)
from crawler.politeness import MAX_CONSECUTIVE_FAILURES
from parsers import GpxParser, HikrParser
from parsers.gpx_parser import GpxParseError
from parsers.grades import TOUR_TYPES, is_grade
from storage import TourStore, TourStoreError
from storage.tour_store import DEFAULT_DB_PATH, STATUS_FAILED, STATUS_STORED


# Echte Hikr Touren, bewusst mit Bandbreite ausgewaehlt: Wandern bis Hochtour,
# mit und ohne GPX Datei, Titel mit Umlauten und Sonderzeichen.
TOUR_URLS = [
    "https://www.hikr.org/tour/post203736.html",  # Ortler, Hochtour ZS-, mit GPX
    "https://www.hikr.org/tour/post203556.html",  # Schaechentaler Windgaellen, T5, mit GPX
    "https://www.hikr.org/tour/post203847.html",  # Plenge-Ueberschreitung, T4, mit GPX
    "https://www.hikr.org/tour/post203814.html",  # Ronengrat, T4, mit GPX
    "https://www.hikr.org/tour/post203791.html",  # Fuersten- und Schwesternsteig, T4, mit GPX
    "https://www.hikr.org/tour/post203029.html",  # Passo Bornengo, T3, mit GPX
    "https://www.hikr.org/tour/post180799.html",  # Meraner Hoehenweg, T2, mit GPX
    "https://www.hikr.org/tour/post203714.html",  # Wiesinger Bichl, T1, mit GPX
    "https://www.hikr.org/tour/post203861.html",  # Fuorcla da Punteglias, T3+, ohne GPX
    "https://www.hikr.org/tour/post203232.html",  # Leiterkopf, T3, ohne GPX
    "https://www.hikr.org/tour/post203853.html",  # Segantinihuette, T2, ohne GPX
    "https://www.hikr.org/tour/post203470.html",  # Stadtwanderung St. Gallen, T1, ohne GPX
]

HTML_DIR = Path("data/html")
GPX_DIR = Path("data/gpx")

# Pause zwischen zwei Touren, wenn run_tours ohne gedrosselten Downloader
# laeuft. Echte Laeufe ueber main regelt der RateLimiter je Anfrage.
REQUEST_DELAY_SECONDS = 1.5

# Bereits geladene HTML Dateien werden wiederverwendet. Das macht wiederholte
# Laeufe schnell und erspart dem Server unnoetige Zugriffe.
REUSE_LOCAL_HTML = True

# Optionen, die nur zusammen mit --discover einen Sinn ergeben.
DISCOVERY_ONLY_OPTIONS = (
    "region", "kategorie", "von", "bis", "max", "nur_urls", "schwierigkeit", "tourtyp",
)


def process_tour(
    url: str,
    downloader: Downloader,
    hikr_parser: HikrParser,
    gpx_parser: GpxParser,
    html_dir: Path = HTML_DIR,
    gpx_dir: Path = GPX_DIR,
) -> dict:
    """
    Laedt eine Tour, liest die Metadaten und ergaenzt die Distanz aus GPX.
    Ist nur die GPX Datei dauerhaft unbrauchbar, kommt die Tour ohne GPX
    zurueck, statt verloren zu gehen.
    """
    # Ein Dateiname je Tour, sonst ueberschreiben sich die Seiten gegenseitig.
    html_path = Path(html_dir) / Path(urlparse(url).path).name

    if REUSE_LOCAL_HTML and html_path.exists():
        print(f"    HTML bereits vorhanden: {html_path}")
    else:
        downloader.download_url(url, html_path)

    metadata = hikr_parser.parse_local_html(html_path, base_url=url)
    metadata["source_url"] = url
    metadata["gpx_path"] = None

    gpx_url = metadata["gpx_url"]
    if gpx_url is None:
        print("    keine GPX Datei verlinkt")
        return metadata

    try:
        gpx_path = downloader.download_gpx(
            gpx_url,
            title=metadata["title"],
            date_iso=metadata["date_iso"],
            save_dir=gpx_dir,
        )
        distance = gpx_parser.parse_local_gpx(gpx_path)["distance_km"]
    except (DownloadError, GpxParseError) as exc:
        # Ein dauerhaft kaputter Anhang darf die lesbare Tour nicht mitreissen,
        # sonst ginge sie als fehlgeschlagen fuer immer verloren. Voruebergehende
        # Fehler und Sperren laufen weiter nach oben: Die Tour bleibt dann offen
        # und bekommt ihre GPX Datei im naechsten Lauf.
        if not is_permanent_failure(exc):
            raise
        print(f"    GPX Datei unbrauchbar, Tour bleibt ohne GPX: {exc}")
        return metadata

    metadata["gpx_path"] = str(gpx_path)
    metadata["distance"] = distance
    return metadata


def is_permanent_failure(exc: Exception) -> bool:
    """
    Dauerhaft heisst: ein spaeterer Lauf scheiterte am selben Punkt, etwa bei
    HTTP 404 oder einer unlesbaren GPX Datei. Netzstoerungen, Datenbank und
    Dateisystem gelten als voruebergehend, die URL bleibt dann offen.
    """
    if isinstance(exc, (TransientDownloadError, CrawlBlockedError)):
        return False
    return isinstance(exc, (DownloadError, GpxParseError))


def run_tours(
    urls: list[str],
    html_dir: Path = HTML_DIR,
    gpx_dir: Path = GPX_DIR,
    delay: float = REQUEST_DELAY_SECONDS,
    database: TourStore | None = None,
    downloader: Downloader | None = None,
) -> tuple[list[dict], list[tuple[str, Exception]]]:
    """
    Arbeitet die Liste ab und liefert Ergebnisse und Fehlschlaege getrennt.
    Eine einzelne kaputte Tour darf den Lauf ueber die uebrigen nicht beenden.

    Mit einer Ablage gilt: Gespeicherte und dauerhaft fehlgeschlagene URLs
    werden uebersprungen, ohne eine einzige Anfrage. Verweigert Hikr den
    Zugriff oder scheitern mehrere Touren in Folge, endet der ganze Lauf.
    """
    html_dir, gpx_dir = Path(html_dir), Path(gpx_dir)
    html_dir.mkdir(parents=True, exist_ok=True)
    gpx_dir.mkdir(parents=True, exist_ok=True)

    downloader = downloader or Downloader()
    hikr_parser = HikrParser()
    gpx_parser = GpxParser()

    results: list[dict] = []
    failures: list[tuple[str, Exception]] = []
    consecutive_failures = 0

    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] {url}")

        if database is not None:
            reason = database.skip_reason(url)
            if reason is not None:
                print(f"    uebersprungen, {reason}")
                continue

        try:
            metadata = process_tour(
                url, downloader, hikr_parser, gpx_parser, html_dir, gpx_dir
            )
            # Direkt ablegen, damit ein Abbruch mitten im Lauf die bereits
            # gelesenen Touren nicht verwirft.
            if database is not None:
                database.upsert_tour(metadata)
                database.record_url_status(url, STATUS_STORED)
            results.append(metadata)
            consecutive_failures = 0
        except CrawlBlockedError as exc:
            # Die Gegenseite will, dass wir aufhoeren. Die restlichen URLs
            # bleiben offen und werden nicht angefragt.
            print(f"    Lauf abgebrochen, {exc}")
            failures.append((url, exc))
            break
        except (DownloadError, GpxParseError, OSError, TourStoreError) as exc:
            # Erwartbare Stoerungen: Netz, HTTP Fehler, kaputte GPX,
            # Dateisystem, Datenbank.
            # Alles andere lassen wir bewusst durchschlagen, das waeren Fehler
            # im eigenen Code und die sollen laut auffallen.
            print(f"    uebersprungen, {type(exc).__name__}: {exc}")
            failures.append((url, exc))
            if database is not None and is_permanent_failure(exc):
                database.record_url_status(url, STATUS_FAILED)

            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(
                    f"    Lauf abgebrochen nach {consecutive_failures} "
                    f"Fehlschlaegen in Folge"
                )
                break

        if index < len(urls) and delay:
            time.sleep(delay)

    return results, failures


def discover_urls(
    discovery: HikrDiscovery,
    store: TourStore,
    region: int | str,
    kategorie: str,
    von: object = None,
    bis: object = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    schwierigkeit: str | Sequence[str] | None = None,
    tourtyp: Optional[str] = None,
) -> list[str]:
    """
    Stellt die URLs fuer einen Discovery Lauf zusammen.

    Zuerst kommen offene URLs frueherer Laeufe derselben Suche, etwa aus
    einem Lauf mit --nur-urls oder nach einer Netzstoerung. Nur fuer den
    Rest wird auf Hikr gesucht, und zwar dort, wo die Suche zuletzt stand,
    eine Seite frueher als Ueberlappung. Ist die Suche schon vollstaendig,
    wird nur oben nach neuen Berichten gesehen.

    Ein Filter auf Schwierigkeit oder Tourtyp ist eine eigene Suche, mit
    eigenem Suchstand und eigenen offenen URLs unter search_key, etwa
    ped:t4,t5,t6 oder alp:ws,zs|ski-hochtour.
    """
    validate_max_results(max_results)
    region_id = resolve_region(region)
    code = resolve_category(kategorie)
    date_from, date_to = date_bounds(von, bis)
    terms = difficulty_terms(schwierigkeit)
    tourtyp = validate_tour_type(tourtyp)
    key = search_key(code, terms, tourtyp)

    pending = store.pending_urls(region_id, key, date_from, date_to, limit=max_results)
    remaining = max_results - len(pending)
    if remaining <= 0:
        print(f"Discovery: {len(pending)} offene URLs aus frueheren Laeufen, keine Suche noetig")
        return pending

    progress = store.get_progress(region_id, key, date_from, date_to)
    completed_before = bool(progress and progress["completed"])
    if progress is None or completed_before:
        start_skip = 0
    else:
        start_skip = max(0, progress["resume_skip"] - PAGE_SIZE)

    result = discovery.discover(
        region_id,
        code,
        remaining,
        von=date_from,
        bis=date_to,
        is_known=store.is_known_url,
        start_skip=start_skip,
        stop_at_known_page=completed_before,
        schwierigkeit=terms,
        tourtyp=tourtyp,
    )

    store.add_discovered(
        [(entry.url, entry.tour_date) for entry in result.found], region_id, key
    )
    completed = result.completed or completed_before
    store.save_progress(region_id, key, date_from, date_to, result.resume_skip, completed)

    state = "vollstaendig durchsucht" if completed else f"weiter ab skip={result.resume_skip}"
    print(
        f"Discovery region{region_id}/{key}: {len(pending)} offen aus frueheren Laeufen, "
        f"{len(result.found)} neu gefunden, {result.pages_read} Listenseiten gelesen, "
        f"Suchbereich {state}"
    )
    return pending + result.urls


def print_summary(results: list[dict], failures: list[tuple[str, Exception]]) -> None:
    """Gibt die gesammelten Touren als sortierte Tabelle aus."""
    print()
    print(f"{'Datum':<11} {'Distanz':>9}  {'Schwierigkeit':<22} Titel")
    print("-" * 92)

    for metadata in sorted(results, key=lambda item: item.get("date_iso") or ""):
        distance = metadata.get("distance")
        distance_text = f"{distance:.2f} km" if distance is not None else "-"
        difficulty = (
            metadata.get("difficulty_ski")
            or metadata.get("difficulty_alpine")
            or metadata.get("difficulty_hiking")
            or metadata.get("difficulty_climbing")
            or "-"
        )
        print(
            f"{metadata.get('date_iso') or '-':<11} {distance_text:>9}  "
            f"{difficulty[:22]:<22} {str(metadata.get('title'))[:40]}"
        )

    with_gpx = sum(1 for metadata in results if metadata.get("gpx_path"))
    print()
    print(
        f"{len(results)} Touren gelesen, {with_gpx} mit GPX Datei, "
        f"{len(failures)} fehlgeschlagen"
    )
    for url, exc in failures:
        print(f"  fehlgeschlagen: {url} ({type(exc).__name__})")


def parse_grade(value: str) -> str:
    """Laesst nur echte Stufen zu, etwa T4, WS, ZS+ oder III."""
    if not is_grade(value):
        raise argparse.ArgumentTypeError(
            f"{value!r} ist keine Schwierigkeitsstufe. Erlaubt sind etwa T4, WS, ZS+, S oder III"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """Ohne Optionen die feste Liste, mit --discover die Suche nach Kriterien."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Laedt Hikr Touren und legt sie in der lokalen Tourdatenbank ab. "
            "Ohne Optionen wird die feste Liste TOUR_URLS abgearbeitet."
        ),
        epilog=(
            "Beispiele:\n"
            "  python main.py\n"
            "  python main.py --discover --region 146 --kategorie skitouren --max 20\n"
            "  python main.py --discover --region Uri --kategorie skitouren "
            "--von 2020 --bis 2026 --max 90\n"
            "  python main.py --discover --region 146 --kategorie ski --nur-urls\n"
            "  python main.py --discover --region 146 --kategorie wandern "
            "--von 2026 --bis 2026 --schwierigkeit T4 T5 T6\n"
            "  python main.py --discover --region 146 --kategorie hochtouren "
            "--von 2026 --bis 2026 --tourtyp ski-hochtour --schwierigkeit WS ZS\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Touren nach Kriterien auf Hikr suchen statt TOUR_URLS zu verwenden. "
        "Die Suche laeuft nur mit dieser Option",
    )
    parser.add_argument("--region", help="Region als ID wie 146 oder als Name wie Uri")
    parser.add_argument(
        "--kategorie", help="skitouren, hochtouren, wandern, klettern ... oder Code wie ski"
    )
    parser.add_argument("--von", metavar="JAHR_ODER_DATUM", help="Tourdatum ab, z.B. 2020")
    parser.add_argument("--bis", metavar="JAHR_ODER_DATUM", help="Tourdatum bis, z.B. 2026")
    parser.add_argument(
        "--schwierigkeit",
        nargs="+",
        action="extend",
        type=parse_grade,
        metavar="STUFE",
        help="Nur Eintraege mit dieser Stufe laden, auf irgendeiner Skala, z.B. "
        "T4 T5 T6 fuer Alpinwanderungen oder WS ZS. ZS trifft ZS-, ZS und ZS+",
    )
    parser.add_argument(
        "--tourtyp",
        choices=TOUR_TYPES,
        help="Nur Touren mit Hochtourennote dieses Typs: ski-hochtour mit Skinote, "
        "alpinwandern-hochtour mit T4 bis T6, hochtour ohne beides",
    )
    parser.add_argument(
        "--max",
        type=int,
        metavar="ANZAHL",
        help=f"Hoechstens so viele neue Touren je Lauf, Standard {DEFAULT_MAX_RESULTS}, "
        f"Obergrenze {MAX_RESULTS_LIMIT}",
    )
    parser.add_argument(
        "--nur-urls",
        action="store_true",
        help="Nur die gefundenen URLs anzeigen und fuer spaeter vormerken, keine Tour laden",
    )
    parser.add_argument(
        "--datenbank",
        default=str(DEFAULT_DB_PATH),
        metavar="PFAD",
        help=f"Pfad zur Ablage, Standard {DEFAULT_DB_PATH}",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Ohne Optionen wird die feste Liste TOUR_URLS abgearbeitet. Die Discovery
    laeuft ausschliesslich mit --discover, nie beim blossen Start.

    Rueckgabewert: 0 Erfolg, 1 Fehler, 2 ungueltige Kriterien,
    3 Hikr hat den Zugriff verweigert.
    """
    # Die Windows Konsole laeuft oft mit cp1252. Ein Titel mit einem Zeichen
    # ausserhalb dieser Tabelle wuerde den Lauf sonst mit einem
    # UnicodeEncodeError beenden, Ersatzzeichen sind das kleinere Uebel.
    sys.stdout.reconfigure(errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)

    stray = [
        "--" + name.replace("_", "-")
        for name in DISCOVERY_ONLY_OPTIONS
        if getattr(args, name) is not None and getattr(args, name) is not False
    ]
    if not args.discover and stray:
        parser.error(f"{', '.join(stray)} gilt nur zusammen mit --discover")
    if args.discover and not (args.region and args.kategorie):
        parser.error("--discover braucht --region und --kategorie")

    failures: list[tuple[str, Exception]] = []
    try:
        with TourStore(args.datenbank) as store:
            downloader = build_polite_downloader()

            if args.discover:
                max_results = args.max if args.max is not None else DEFAULT_MAX_RESULTS
                try:
                    discovery = HikrDiscovery(downloader)
                    urls = discover_urls(
                        discovery, store, args.region, args.kategorie,
                        args.von, args.bis, max_results,
                        schwierigkeit=args.schwierigkeit,
                        tourtyp=args.tourtyp,
                    )
                except DiscoveryError as exc:
                    print(f"Discovery nicht moeglich: {exc}", file=sys.stderr)
                    return 2
                except CrawlBlockedError as exc:
                    print(f"Hikr hat den Zugriff verweigert, Lauf beendet: {exc}", file=sys.stderr)
                    return 3
                except DownloadError as exc:
                    print(f"Discovery fehlgeschlagen: {exc}", file=sys.stderr)
                    return 1

                print()
                print(f"{len(urls)} URLs fuer diesen Lauf:")
                for url in urls:
                    print(f"  {url}")
                if args.nur_urls:
                    print("Nur angezeigt, keine Tour geladen. Die URLs bleiben fuer den naechsten Lauf offen.")
                    return 0
            else:
                urls = TOUR_URLS

            results, failures = run_tours(
                urls,
                html_dir=HTML_DIR,
                gpx_dir=GPX_DIR,
                delay=0,
                database=store,
                downloader=downloader,
            )
            print_summary(results, failures)
            print(f"Datenbank {store.db_path}: {store.count()} Touren abgelegt")
    except TourStoreError as exc:
        print(f"Datenbankfehler: {exc}", file=sys.stderr)
        return 1

    if any(isinstance(exc, CrawlBlockedError) for _, exc in failures):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
