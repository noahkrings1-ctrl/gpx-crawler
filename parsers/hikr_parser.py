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
        region_country, region_main, region_area = self._split_region(fiche.get("region"))

        metadata = {
            "title": self._extract_title(soup),
            "region": fiche.get("region"),
            "date": fiche.get("date"),
            "date_iso": self._parse_date_iso(fiche.get("date")),
            "difficulty_hiking": fiche.get("difficulty_hiking"),
            "difficulty_alpine": fiche.get("difficulty_alpine"),
            "difficulty_climbing": fiche.get("difficulty_climbing"),
            "region_leaf": self._region_leaf(fiche.get("region")),
            "region_country": region_country,
            "region_main": region_main,
            "region_area": region_area,
            "sport": self._derive_sport(fiche),
            "elevation_gain": fiche.get("elevation_gain"),
            "elevation_gain_m": self._parse_meters(fiche.get("elevation_gain")),
            "elevation_loss": fiche.get("elevation_loss"),
            "elevation_loss_m": self._parse_meters(fiche.get("elevation_loss")),
            "time_required": fiche.get("time_required"),
            "time_required_min": self._parse_minutes(fiche.get("time_required")),
            "duration_days": self._parse_days(fiche.get("time_required")),
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

    def _region_leaf(self, region: Optional[str]) -> Optional[str]:
        """
        Aus "Welt , Schweiz , Uri" wird Uri, der spezifischste Teil der Kette.
        Damit laesst sich spaeter gezielt nach einer Region filtern, ohne
        jedesmal den ganzen Pfad zu vergleichen.
        """
        if not region:
            return None
        parts = [part.strip() for part in region.split(",") if part.strip()]
        return parts[-1] if parts else None

    def _split_region(
        self, region: Optional[str]
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Zerlegt die Regionskette in Land, Hauptregion und Gebiet.

        Aus "Welt , Schweiz , Graubuenden , Oberengadin" wird
        (Schweiz, Graubuenden, Oberengadin), aus "Welt , Liechtenstein"
        wird (Liechtenstein, None, None).

        Die erste Stufe heisst bei Hikr immer Welt und traegt keine
        Information, sie faellt weg. Die mittlere Stufe ist in der Schweiz
        der Kanton, in Oesterreich aber eine Gebirgsgruppe wie
        "Zentrale Ostalpen". Deshalb der neutrale Name Hauptregion, eine
        Spalte namens Kanton waere fuer alle uebrigen Laender falsch.
        """
        if not region:
            return (None, None, None)

        parts = [part.strip() for part in region.split(",") if part.strip()]
        if parts and parts[0].lower() == "welt":
            parts = parts[1:]

        # Auf drei Stufen auffuellen, fehlende bleiben None.
        padded = (parts + [None, None, None])[:3]
        return (padded[0], padded[1], padded[2])

    def _derive_sport(self, fiche: dict) -> Optional[str]:
        """
        Hikr fuehrt je Sportart eine eigene Schwierigkeitsskala. Welche
        gefuellt ist, verraet die Art der Tour.

        Die Reihenfolge ist nicht beliebig. Die Hochtouren Skala steht nur
        bei echten Hochtouren. Eine UIAA Note neben einer T Note markiert
        dagegen nur eine Kletterstelle, der Charakter bleibt eine Wanderung.
        Deshalb schlaegt Wandern das Klettern, aber nicht die Hochtour.
        """
        if fiche.get("difficulty_alpine"):
            return "Hochtour"
        if fiche.get("difficulty_hiking"):
            return "Wandern"
        if fiche.get("difficulty_climbing"):
            return "Klettern"
        return None

    def _parse_meters(self, value: Optional[str]) -> Optional[int]:
        """
        Aus "1270 m" wird 1270. Eine Schweizer Tausendertrennung wie 1'270
        wird mit entfernt. Ohne Zahl gibt es None.
        """
        if not value:
            return None
        match = re.search(r"(\d[\d'\s.]*)\s*m", value)
        if not match:
            return None
        digits = re.sub(r"[^0-9]", "", match.group(1))
        return int(digits) if digits else None

    def _parse_minutes(self, value: Optional[str]) -> Optional[int]:
        """
        Aus "5:00" werden 300 Minuten. Mehrtaegige Angaben wie "6 Tage"
        ergeben bewusst None, siehe _parse_days. Eine Umrechnung in Minuten
        waere irrefuehrend, weil sie Gehzeit und Kalendertage vermischt.
        """
        if not value:
            return None
        match = re.search(r"(\d{1,3}):(\d{2})", value)
        if not match:
            return None
        return int(match.group(1)) * 60 + int(match.group(2))

    def _parse_days(self, value: Optional[str]) -> Optional[int]:
        """Aus "6 Tage" wird 6. Alles andere ergibt None."""
        if not value:
            return None
        match = re.search(r"(\d{1,2})\s*Tage?", value, re.IGNORECASE)
        return int(match.group(1)) if match else None

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
