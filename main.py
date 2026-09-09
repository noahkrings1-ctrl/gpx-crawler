import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from crawler import Downloader
from crawler.downloader import DownloadError
from parsers import GpxParser, HikrParser
from parsers.gpx_parser import GpxParseError
from storage import TourStore, TourStoreError


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

# Hoeflichkeitspause zwischen zwei Seitenaufrufen. Wir sind Gast auf Hikr.
REQUEST_DELAY_SECONDS = 1.5

# Bereits geladene HTML Dateien werden wiederverwendet. Das macht wiederholte
# Laeufe schnell und erspart dem Server unnoetige Zugriffe.
REUSE_LOCAL_HTML = True


def process_tour(
    url: str,
    downloader: Downloader,
    hikr_parser: HikrParser,
    gpx_parser: GpxParser,
    html_dir: Path = HTML_DIR,
    gpx_dir: Path = GPX_DIR,
) -> dict:
    """Laedt eine Tour, liest die Metadaten und ergaenzt die Distanz aus GPX."""
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

    gpx_path = downloader.download_gpx(
        gpx_url,
        title=metadata["title"],
        date_iso=metadata["date_iso"],
        save_dir=gpx_dir,
    )
    metadata["gpx_path"] = str(gpx_path)
    metadata["distance"] = gpx_parser.parse_local_gpx(gpx_path)["distance_km"]
    return metadata


def run_tours(
    urls: list[str],
    html_dir: Path = HTML_DIR,
    gpx_dir: Path = GPX_DIR,
    delay: float = REQUEST_DELAY_SECONDS,
    database: TourStore | None = None,
) -> tuple[list[dict], list[tuple[str, Exception]]]:
    """
    Arbeitet die Liste ab und liefert Ergebnisse und Fehlschlaege getrennt.
    Eine einzelne kaputte Tour darf den Lauf ueber die uebrigen nicht beenden.
    """
    html_dir, gpx_dir = Path(html_dir), Path(gpx_dir)
    html_dir.mkdir(parents=True, exist_ok=True)
    gpx_dir.mkdir(parents=True, exist_ok=True)

    downloader = Downloader()
    hikr_parser = HikrParser()
    gpx_parser = GpxParser()

    results: list[dict] = []
    failures: list[tuple[str, Exception]] = []

    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] {url}")
        try:
            metadata = process_tour(
                url, downloader, hikr_parser, gpx_parser, html_dir, gpx_dir
            )
            # Direkt ablegen, damit ein Abbruch mitten im Lauf die bereits
            # gelesenen Touren nicht verwirft.
            if database is not None:
                database.upsert_tour(metadata)
            results.append(metadata)
        except (DownloadError, GpxParseError, OSError, TourStoreError) as exc:
            # Erwartbare Stoerungen: Netz, HTTP Fehler, kaputte GPX,
            # Dateisystem, Datenbank.
            # Alles andere lassen wir bewusst durchschlagen, das waeren Fehler
            # im eigenen Code und die sollen laut auffallen.
            print(f"    uebersprungen, {type(exc).__name__}: {exc}")
            failures.append((url, exc))

        if index < len(urls):
            time.sleep(delay)

    return results, failures


def print_summary(results: list[dict], failures: list[tuple[str, Exception]]) -> None:
    """Gibt die gesammelten Touren als sortierte Tabelle aus."""
    print()
    print(f"{'Datum':<11} {'Distanz':>9}  {'Schwierigkeit':<22} Titel")
    print("-" * 92)

    for metadata in sorted(results, key=lambda item: item["date_iso"] or ""):
        distance = metadata["distance"]
        distance_text = f"{distance:.2f} km" if distance is not None else "-"
        difficulty = (
            metadata["difficulty_alpine"]
            or metadata["difficulty_hiking"]
            or metadata["difficulty_climbing"]
            or "-"
        )
        print(
            f"{metadata['date_iso'] or '-':<11} {distance_text:>9}  "
            f"{difficulty[:22]:<22} {str(metadata['title'])[:40]}"
        )

    with_gpx = sum(1 for metadata in results if metadata["gpx_path"])
    print()
    print(
        f"{len(results)} Touren gelesen, {with_gpx} mit GPX Datei, "
        f"{len(failures)} fehlgeschlagen"
    )
    for url, exc in failures:
        print(f"  fehlgeschlagen: {url} ({type(exc).__name__})")


def main() -> None:
    """Arbeitet die Liste TOUR_URLS ab und gibt eine Uebersicht aus."""
    # Die Windows Konsole laeuft oft mit cp1252. Ein Titel mit einem Zeichen
    # ausserhalb dieser Tabelle wuerde den Lauf sonst mit einem
    # UnicodeEncodeError beenden, Ersatzzeichen sind das kleinere Uebel.
    sys.stdout.reconfigure(errors="replace")

    with TourStore() as database:
        results, failures = run_tours(TOUR_URLS, database=database)
        print_summary(results, failures)
        print(f"Datenbank {database.db_path}: {database.count()} Touren abgelegt")


if __name__ == "__main__":
    main()
