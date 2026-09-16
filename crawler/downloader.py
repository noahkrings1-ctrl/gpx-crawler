import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .politeness import (
    MIN_DELAY_SECONDS,
    RETRYABLE_STATUS,
    RateLimiter,
    RetryPolicy,
    RobotsPolicy,
    is_challenge,
    parse_retry_after,
)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Fuer GPX Dateien ueberschreiben wir den auf HTML ausgelegten Accept Header.
GPX_HEADERS = {
    "Accept": "application/gpx+xml,application/xml;q=0.9,*/*;q=0.8",
}

UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
}

MAX_SLUG_LENGTH = 80


def slugify(text: str) -> str:
    """
    Wandelt einen Titel in einen dateisystemtauglichen Namen um.
    Umlaute werden ausgeschrieben, alles uebrige auf a-z, 0-9 und
    Bindestriche reduziert. Das entfernt nebenbei die unter Windows
    verbotenen Zeichen wie Schraegstrich, Doppelpunkt oder Fragezeichen.
    """
    slug = text.strip().lower()
    for umlaut, replacement in UMLAUT_MAP.items():
        slug = slug.replace(umlaut, replacement)

    # Restliche Akzente zerlegen und die Diakritika verwerfen, z.B. aus e wird e.
    slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:MAX_SLUG_LENGTH].strip("-")


class DownloadError(Exception):
    """Raised when downloading a page fails."""


class TransientDownloadError(DownloadError):
    """
    Voruebergehende Stoerung, etwa ein Netzfehler oder HTTP 503. Die URL
    gilt nicht als gecrawlt, ein spaeterer Lauf darf es erneut versuchen.
    """


class CrawlBlockedError(DownloadError):
    """
    Die Gegenseite verlangt, dass wir aufhoeren: HTTP 403, HTTP 429 ohne
    vertretbare Wartezeit, eine Cloudflare Pruefung oder eine Sperre in
    robots.txt. Der ganze Lauf endet, nicht nur die einzelne URL.
    """


class Downloader:
    """
    Download web pages and save them to the local file system.

    Drossel, robots.txt Pruefung und Wiederholungen sind optional. Ohne sie
    verhaelt sich der Downloader wie bisher, echte Laeufe bekommen alle drei
    ueber build_polite_downloader.
    """

    def __init__(
        self,
        headers: dict | None = None,
        timeout: int = 10,
        limiter: RateLimiter | None = None,
        robots: RobotsPolicy | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.timeout = timeout
        self.limiter = limiter
        self.robots = robots
        self.retry = retry

    def download_url(self, url: str, save_path: str | Path, encoding: str = "utf-8") -> Path:
        """Download a URL and save the HTML to the local file system."""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        response = self._get(url, self.headers, action="download")

        html_text = response.text
        self._write_atomic(save_path, html_text.encode(encoding))
        print(f"[downloader] {url} -> {save_path} ({len(html_text)} chars)")
        return save_path

    def download_gpx(
        self,
        url: str,
        title: str | None = None,
        date_iso: str | None = None,
        save_dir: str | Path = "data/gpx",
    ) -> Path:
        """
        Laedt eine GPX Datei und legt sie unter Datum und Tourtitel ab,
        zum Beispiel 2026-07-12-sunnig-wichel-via-nordgrat.gpx

        Liegt die Datei schon vor, gibt es keine Anfrage. Gespeichert wird nur
        eine gepruefte GPX Datei, und das atomar, eine vorhandene Datei ist
        also vollstaendig.
        """
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / self._build_gpx_filename(url, title, date_iso)

        if save_path.exists():
            print(f"[downloader] GPX bereits vorhanden: {save_path}")
            return save_path

        response = self._get(url, {**self.headers, **GPX_HEADERS}, action="download")

        # Bytes statt Text, damit die Encoding Deklaration im GPX Kopf gueltig bleibt.
        content = response.content
        if not self._looks_like_gpx(content):
            raise DownloadError(f"Response from {url} is not a GPX file")

        self._write_atomic(save_path, content)
        print(f"[downloader] {url} -> {save_path} ({len(content)} bytes)")
        return save_path

    def fetch_html(self, url: str) -> str:
        """Return HTML content from a URL without saving it."""
        return self._get(url, self.headers, action="fetch").text

    def fetch_robots(self, url: str) -> tuple[int, str]:
        """
        Laedt robots.txt gedrosselt, aber ohne sie selbst zu pruefen. Ein
        Netzfehler ergibt Status 0, die RobotsPolicy sperrt dann den Host.
        """
        if self.limiter is not None:
            self.limiter.wait(url)
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
        except requests.RequestException:
            return 0, ""
        return response.status_code, response.text

    def _get(self, url: str, headers: dict, action: str) -> requests.Response:
        """
        Eine Anfrage nach den Regeln aus crawler/politeness.py.

        Reihenfolge: robots.txt pruefen, Pause einhalten, anfragen, Antwort
        einordnen. 403 und Cloudflare Pruefungen beenden den Lauf sofort.
        429 wird nur mit vertretbarem Retry-After einmal abgewartet.
        Netzfehler und 502, 503, 504 werden nach der RetryPolicy wiederholt.
        Alles andere ausser 200 ist ein dauerhafter Fehler.
        """
        verb = "downloading" if action == "download" else "fetching"

        crawl_delay = None
        if self.robots is not None:
            if not self.robots.allowed(url):
                raise CrawlBlockedError(f"robots.txt disallows {url}")
            crawl_delay = self.robots.crawl_delay(url)

        attempt = 0
        waited_for_retry_after = False
        while True:
            if self.limiter is not None:
                self.limiter.wait(url, crawl_delay)

            try:
                response = requests.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if self._may_retry(attempt):
                    attempt += 1
                    self._pause(self.retry.backoff(attempt))
                    continue
                raise TransientDownloadError(
                    f"Network error while {verb} {url}: {exc}"
                ) from exc

            status = response.status_code
            response_headers = getattr(response, "headers", None) or {}

            if is_challenge(response_headers):
                raise CrawlBlockedError(
                    f"Failed to {action} {url}: Cloudflare challenge, access blocked"
                )
            if status == 200:
                return response
            if status == 403:
                raise CrawlBlockedError(
                    f"Failed to {action} {url}: HTTP 403, access blocked"
                )
            if status == 429:
                retry_after = parse_retry_after(response_headers.get("Retry-After"))
                if (
                    self.retry is not None
                    and not waited_for_retry_after
                    and retry_after is not None
                    and retry_after <= self.retry.max_retry_after_seconds
                ):
                    waited_for_retry_after = True
                    self._pause(retry_after)
                    continue
                raise CrawlBlockedError(
                    f"Failed to {action} {url}: HTTP 429, too many requests"
                )
            if status in RETRYABLE_STATUS:
                if self._may_retry(attempt):
                    attempt += 1
                    self._pause(self.retry.backoff(attempt))
                    continue
                raise TransientDownloadError(f"Failed to {action} {url}: HTTP {status}")

            raise DownloadError(f"Failed to {action} {url}: HTTP {status}")

    def _may_retry(self, attempt: int) -> bool:
        return self.retry is not None and attempt < self.retry.max_retries

    def _pause(self, seconds: float) -> None:
        if self.limiter is not None:
            self.limiter.pause(seconds)
        elif seconds > 0:
            time.sleep(seconds)

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        """
        Schreibt erst in eine Nebendatei und benennt sie dann um. Bricht ein
        Lauf mitten im Schreiben ab, bleibt keine halbe Datei zurueck, die der
        naechste Lauf faelschlich als vorhanden wiederverwenden wuerde.
        """
        partial = path.with_name(path.name + ".part")
        partial.write_bytes(data)
        partial.replace(path)

    def _build_gpx_filename(
        self, url: str, title: str | None, date_iso: str | None
    ) -> str:
        """
        Setzt den Dateinamen aus Datum und Titel zusammen. Das Datum steht
        vorne, damit der Ordner von allein chronologisch sortiert. Fehlen
        beide Angaben, faellt der Name auf den Basisnamen der URL zurueck.
        """
        parts = [slugify(part) for part in (date_iso or "", title or "")]
        parts = [part for part in parts if part]
        if not parts:
            return self._filename_from_url(url)
        return "-".join(parts) + ".gpx"

    def _filename_from_url(self, url: str) -> str:
        """Zieht den Dateinamen aus dem Pfad der URL, ohne Query String."""
        name = Path(unquote(urlparse(url).path)).name
        if not name.lower().endswith(".gpx"):
            raise DownloadError(f"Cannot derive a GPX file name from {url}")
        return name

    @staticmethod
    def _looks_like_gpx(content: bytes) -> bool:
        """
        Hikr antwortet auf tote Links mit einer HTML Seite und Status 200.
        Jede echte GPX Datei traegt ihr gpx Wurzelelement gleich am Anfang.
        """
        return b"<gpx" in content[:1024].lower()


def build_polite_downloader(min_delay: float = MIN_DELAY_SECONDS) -> Downloader:
    """
    Der Downloader fuer echte Laeufe: Drossel, robots.txt und
    Wiederholungsregeln sind eingeschaltet. Das Anlegen selbst stellt noch
    keine Anfrage, robots.txt wird erst vor dem ersten Abruf geladen.
    """
    downloader = Downloader(limiter=RateLimiter(min_delay), retry=RetryPolicy())
    downloader.robots = RobotsPolicy(
        downloader.headers["User-Agent"], downloader.fetch_robots
    )
    return downloader
