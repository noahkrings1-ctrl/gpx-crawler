from pathlib import Path

import requests


DEFAULT_HEADERS = {
    "User-Agent": "GPX Crawler/1.0 (+https://github.com/)",
}


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
        return save_path

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
