import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests


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


class Downloader:
    """Download web pages and save them to a local HTML file."""

    def __init__(self, headers: dict | None = None, timeout: int = 10) -> None:
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.timeout = timeout

    def download_url(self, url: str, save_path: str | Path, encoding: str = "utf-8") -> Path:
        """Download a URL and save the HTML to the local file system."""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DownloadError(f"Network error while downloading {url}: {exc}") from exc

        if response.status_code != 200:
            raise DownloadError(
                f"Failed to download {url}: HTTP {response.status_code}"
            )

        html_text = response.text
        save_path.write_text(html_text, encoding=encoding)
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
        """
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / self._build_gpx_filename(url, title, date_iso)

        headers = {**self.headers, **GPX_HEADERS}
        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DownloadError(f"Network error while downloading {url}: {exc}") from exc

        if response.status_code != 200:
            raise DownloadError(
                f"Failed to download {url}: HTTP {response.status_code}"
            )

        # Bytes statt Text, damit die Encoding Deklaration im GPX Kopf gueltig bleibt.
        content = response.content
        if not self._looks_like_gpx(content):
            raise DownloadError(f"Response from {url} is not a GPX file")

        save_path.write_bytes(content)
        print(f"[downloader] {url} -> {save_path} ({len(content)} bytes)")
        return save_path

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

    def fetch_html(self, url: str) -> str:
        """Return HTML content from a URL without saving it."""
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DownloadError(f"Network error while fetching {url}: {exc}") from exc

        if response.status_code != 200:
            raise DownloadError(
                f"Failed to fetch {url}: HTTP {response.status_code}"
            )

        return response.text
