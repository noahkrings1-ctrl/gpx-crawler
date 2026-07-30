from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class HikrParser:
    """Parse local Hikr.org HTML files and extract tour metadata."""

    def parse_local_html(self, html_path: str | Path, base_url: Optional[str] = None) -> dict:
        """Read an HTML file from disk and return extracted metadata."""
        html_path = Path(html_path)
        html_text = html_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_text, "lxml")

        metadata = {
            "title": self._extract_title(soup),
            "region": self._extract_region(soup),
            "date": self._extract_date(soup),
            "difficulty": self._extract_difficulty(soup),
            "distance": self._extract_distance(soup),
            "elevation_gain": self._extract_elevation_gain(soup),
            "gpx_url": self._extract_gpx_link(soup, base_url=base_url),
        }

        return metadata

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        candidates = ["h1", ".tour_title", ".title", "#title"]
        for selector in candidates:
            element = soup.select_one(selector)
            if element and element.get_text(strip=True):
                return element.get_text(strip=True)
        return None

    def _extract_region(self, soup: BeautifulSoup) -> Optional[str]:
        return self._extract_value_by_labels(
            soup,
            labels=["region", "area", "location", "land"]
        )

    def _extract_date(self, soup: BeautifulSoup) -> Optional[str]:
        # Hikr often uses <time> tags or label/value pairs.
        time_tag = soup.find("time")
        if time_tag and time_tag.get_text(strip=True):
            return time_tag.get_text(strip=True)

        return self._extract_value_by_labels(soup, labels=["date", "day"])

    def _extract_difficulty(self, soup: BeautifulSoup) -> Optional[str]:
        return self._extract_value_by_labels(soup, labels=["difficulty", "diff", "grade"])

    def _extract_distance(self, soup: BeautifulSoup) -> Optional[str]:
        return self._extract_value_by_labels(soup, labels=["distance", "length"])

    def _extract_elevation_gain(self, soup: BeautifulSoup) -> Optional[str]:
        return self._extract_value_by_labels(soup, labels=["elevation", "gain", "up", "ascent"])

    def _extract_gpx_link(self, soup: BeautifulSoup, base_url: Optional[str] = None) -> Optional[str]:
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if ".gpx" in href.lower():
                if base_url is not None:
                    return urljoin(base_url, href)
                return href

        return None

    def _extract_value_by_labels(self, soup: BeautifulSoup, labels: list[str]) -> Optional[str]:
        lower_labels = [label.lower() for label in labels]

        for element in soup.find_all(["span", "strong", "b", "td", "th", "li", "div"]):
            text = element.get_text(" ", strip=True)
            if not text:
                continue

            normalized = text.lower().strip()
            for label in lower_labels:
                if normalized.startswith(label + ":") or normalized.startswith(label + " -"):
                    parts = text.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip()

                if label in normalized and ":" in normalized:
                    parts = normalized.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip()

            # If the label appears inside a text node, look for the next sibling value.
            for label in lower_labels:
                if label in normalized:
                    sibling = element.find_next_sibling()
                    if sibling and sibling.get_text(strip=True):
                        return sibling.get_text(strip=True)

        return None
