import re
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


class HikrParser:
    """Parse local Hikr.org HTML files and extract tour metadata."""

    # Die deutschen Labels auf Hikr. Wir mappen sie auf unsere internen Keys.
    LABEL_MAP = {
        "region": "region",
        "tour datum": "date",
        "wandern schwierigkeit": "difficulty_hiking",
        "hochtouren schwierigkeit": "difficulty_alpine",
        "klettern schwierigkeit": "difficulty_climbing",
        "aufstieg": "elevation_gain",
        "abstieg": "elevation_loss",
        "zeitbedarf": "time_required",
    }

    # Hikr schreibt das Tourdatum deutsch aus, zum Beispiel "12 Juli 2026".
    MONTHS_DE = {
        "januar": 1,
        "februar": 2,
        "maerz": 3,
        "märz": 3,
        "april": 4,
        "mai": 5,
        "juni": 6,
        "juli": 7,
        "august": 8,
        "september": 9,
        "oktober": 10,
        "november": 11,
        "dezember": 12,
    }

    def parse_local_html(self, html_path: str | Path, base_url: Optional[str] = None) -> dict:
        """Read an HTML file from disk and return extracted metadata."""
        html_path = Path(html_path)
        html_text = html_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_text, "lxml")

        fiche = self._extract_fiche_rando(soup)

        metadata = {
            "title": self._extract_title(soup),
            "region": fiche.get("region"),
            "date": fiche.get("date"),
            "date_iso": self._parse_date_iso(fiche.get("date")),
            "difficulty_hiking": fiche.get("difficulty_hiking"),
            "difficulty_alpine": fiche.get("difficulty_alpine"),
            "difficulty_climbing": fiche.get("difficulty_climbing"),
            "elevation_gain": fiche.get("elevation_gain"),
            "elevation_loss": fiche.get("elevation_loss"),
            "time_required": fiche.get("time_required"),
            "distance": None,  # Nicht in HTML vorhanden, kommt spaeter aus GPX
            "gpx_url": self._extract_gpx_link(soup, base_url=base_url),
        }
        return metadata

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Der Tourtitel steht im h1 Tag mit der Klasse title."""
        element = soup.select_one("h1.title")
        if element:
            return element.get_text(strip=True)
        return None

    def _extract_fiche_rando(self, soup: BeautifulSoup) -> dict:
        """
        Liest die Metadaten Tabelle mit der Klasse fiche_rando.
        Struktur ist immer <td class="fiche_rando_b">Label:</td><td class="fiche_rando">Wert</td>.
        """
        result: dict = {}
        label_cells = soup.find_all("td", class_="fiche_rando_b")

        for label_cell in label_cells:
            label_text = label_cell.get_text(strip=True).rstrip(":").strip().lower()
            key = self.LABEL_MAP.get(label_text)
            if key is None:
                continue  # Label interessiert uns nicht, ueberspringen

            value_cell = label_cell.find_next_sibling("td")
            if not isinstance(value_cell, Tag):
                continue

            value = value_cell.get_text(" ", strip=True)
            result[key] = self._clean_value(key, value)

        return result

    def _clean_value(self, key: str, value: str) -> str:
        """
        Feld spezifische Nachbearbeitung. Bei Region entfernen wir das
        Fuellzeichen und behalten die Kette Welt, Schweiz, Uri.
        """
        if key == "region":
            # Aus "Welt » Schweiz » Uri" wird eine Liste, wir behalten aber den String
            return value.replace("»", ",").replace("  ", " ").strip()
        return value.strip()

    def _parse_date_iso(self, value: Optional[str]) -> Optional[str]:
        """
        Normalisiert das Tourdatum auf ISO, also 2026-07-12. Das Rohfeld date
        bleibt daneben erhalten. Sortier- und filterbare Daten brauchen wir
        spaeter fuer die Datenbank und schon jetzt fuer den GPX Dateinamen.
        Nicht lesbare Angaben ergeben None statt eines Fehlers.
        """
        if not value:
            return None

        text = value.strip().lower()

        # Ausgeschriebener Monat, zum Beispiel "12 Juli 2026" oder "12. Juli 2026"
        match = re.fullmatch(r"(\d{1,2})\.?\s+([a-zäöü]+)\.?\s+(\d{4})", text)
        if match:
            day, month_name, year = match.groups()
            month = self.MONTHS_DE.get(month_name)
        else:
            # Numerische Schreibweise, zum Beispiel "12.07.2026"
            match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
            if not match:
                return None
            day, month_raw, year = match.groups()
            month = int(month_raw)

        if month is None:
            return None

        try:
            return date(int(year), month, int(day)).isoformat()
        except ValueError:
            return None  # Zum Beispiel der 32. Juli

    def _extract_gpx_link(self, soup: BeautifulSoup, base_url: Optional[str] = None) -> Optional[str]:
        """
        Findet den ersten Link, der auf eine .gpx Datei zeigt.
        Hikr benutzt absolute URLs auf die Subdomain f.hikr.org.
        """
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if href.lower().endswith(".gpx"):
                if base_url is not None:
                    return urljoin(base_url, href)
                return href
        return None
