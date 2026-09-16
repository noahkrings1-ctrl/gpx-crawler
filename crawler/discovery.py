import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .downloader import UMLAUT_MAP, Downloader


BASE_URL = "https://www.hikr.org"

# Hikr zeigt zehn Berichte je Listenseite und blaettert ueber skip weiter.
PAGE_SIZE = 10

# Grenzen je Aufruf. MAX_RESULTS_LIMIT laesst sich per Parameter nicht
# aufheben, MAX_PAGES_PER_CALL begrenzt die Listenseiten je Aufruf.
DEFAULT_MAX_RESULTS = 20
MAX_RESULTS_LIMIT = 100
MAX_PAGES_PER_CALL = 20

# Kategoriecodes aus den Regionsseiten, Stand September 2026. Deutsche Namen
# und die Codes selbst werden beide akzeptiert.
CATEGORY_CODES = {
    "alle": "tour",
    "tourenberichte": "tour",
    "tour": "tour",
    "wandern": "ped",
    "ped": "ped",
    "hochtouren": "alp",
    "hochtour": "alp",
    "alp": "alp",
    "klettern": "esc",
    "esc": "esc",
    "skitouren": "ski",
    "skitour": "ski",
    "ski": "ski",
    "schneeschuhe": "raq",
    "schneeschuh": "raq",
    "raq": "raq",
    "klettersteig": "via",
    "klettersteige": "via",
    "via": "via",
    "eisklettern": "eis",
    "eis": "eis",
}

CATEGORY_NAMES = (
    "alle", "wandern", "hochtouren", "klettern", "skitouren",
    "schneeschuhe", "klettersteig", "eisklettern",
)

# Region IDs, abgelesen an echten Regionsseiten. Andere Regionen lassen sich
# ueber ihre ID ansprechen, sie steht in der URL der Regionsseite.
REGION_IDS = {
    "Schweiz": 2,
    "Wallis": 3,
    "Graubünden": 4,
    "Freiburg": 6,
    "Waadt": 8,
    "Neuenburg": 12,
    "Bern": 13,
    "Frankreich": 14,
    "Italien": 16,
    "Trentino-Südtirol": 18,
    "Österreich": 33,
    "Tessin": 41,
    "Glarus": 44,
    "St.Gallen": 45,
    "Deutschland": 69,
    "Schwyz": 109,
    "Obwalden": 127,
    "Solothurn": 139,
    "Basel Land": 140,
    "Schaffhausen": 142,
    "Uri": 146,
    "Zürich": 148,
    "Jura": 149,
    "Aargau": 150,
    "Basel Stadt": 153,
    "Nidwalden": 154,
    "Luzern": 162,
    "Appenzell": 171,
    "Zug": 178,
    "Genf": 495,
    "Thurgau": 496,
}

REGION_ALIASES = {
    "st. gallen": 45,
    "sankt gallen": 45,
    "basel-land": 140,
    "baselland": 140,
    "basel-stadt": 153,
}

# Kurzformen der Monate auf den Listenseiten, etwa "19 Mär 26".
MONTHS_SHORT = {
    "jan": 1,
    "feb": 2,
    "maer": 3,
    "mar": 3,
    "mrz": 3,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "okt": 10,
    "oct": 10,
    "nov": 11,
    "dez": 12,
    "dec": 12,
}

POST_URL = re.compile(r"^https://www\.hikr\.org/tour/post\d+\.html$")


class DiscoveryError(Exception):
    """Raised when discovery criteria are invalid or a listing page cannot be read."""


@dataclass(frozen=True)
class ListingEntry:
    """Ein Bericht auf einer Listenseite, mit Tourdatum falls lesbar."""

    url: str
    tour_date: Optional[str]


@dataclass(frozen=True)
class ListingPage:
    entries: list[ListingEntry]
    next_url: Optional[str]
    has_navigator: bool


@dataclass
class DiscoveryResult:
    """
    Ergebnis eines Aufrufs. resume_skip ist die Listenseite, an der ein
    spaeterer Lauf weitermachen kann. completed heisst, dass die Liste oder
    der Datumsbereich zu Ende durchsucht ist.
    """

    region_id: int
    category: str
    date_from: Optional[str]
    date_to: Optional[str]
    found: list[ListingEntry] = field(default_factory=list)
    resume_skip: int = 0
    completed: bool = False
    pages_read: int = 0

    @property
    def urls(self) -> list[str]:
        return [entry.url for entry in self.found]


def _key(text: object) -> str:
    """Klein geschrieben, Umlaute ausgeschrieben, Leerraum zusammengefasst."""
    lowered = str(text).strip().lower()
    for umlaut, replacement in UMLAUT_MAP.items():
        lowered = lowered.replace(umlaut, replacement)
    return re.sub(r"\s+", " ", lowered)


def resolve_region(region: int | str) -> int:
    """Nimmt eine Region als ID oder als hinterlegten Namen entgegen."""
    if isinstance(region, bool):
        raise DiscoveryError(f"{region!r} ist keine Region")

    if isinstance(region, int):
        region_id = region
    else:
        text = str(region).strip()
        if text.isdigit():
            region_id = int(text)
        else:
            lookup = {_key(name): ident for name, ident in REGION_IDS.items()}
            lookup.update(REGION_ALIASES)
            found = lookup.get(_key(text))
            if found is None:
                raise DiscoveryError(
                    f"Region {region!r} ist nicht hinterlegt. Die ID steht in der URL "
                    f"der Regionsseite, fuer Uri etwa region146.html, also --region 146"
                )
            region_id = found

    if region_id <= 0:
        raise DiscoveryError(f"Eine Region ID ist positiv, war {region_id}")
    return region_id


def resolve_category(kategorie: str) -> str:
    """Nimmt eine Kategorie als deutschen Namen oder als Hikr Code entgegen."""
    code = CATEGORY_CODES.get(_key(kategorie))
    if code is None:
        raise DiscoveryError(
            f"Kategorie {kategorie!r} ist unbekannt. Moeglich sind "
            f"{', '.join(CATEGORY_NAMES)} oder die Codes tour, ped, alp, esc, ski, raq, via, eis"
        )
    return code


def validate_max_results(max_results: int) -> int:
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= MAX_RESULTS_LIMIT
    ):
        raise DiscoveryError(
            f"max_results muss eine ganze Zahl zwischen 1 und {MAX_RESULTS_LIMIT} sein, "
            f"war {max_results!r}"
        )
    return max_results


def _date_bound(value: object, end: bool) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-12-31" if end else f"{text}-01-01"
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise DiscoveryError(
            f"{value!r} ist kein Jahr und kein Datum, erlaubt sind 2025 oder 2025-06-01"
        ) from None


def date_bounds(von: object = None, bis: object = None) -> tuple[Optional[str], Optional[str]]:
    """
    Macht aus von und bis einen Datumsbereich. Ein Jahr steht fuer das ganze
    Jahr, von 2020 heisst ab 2020-01-01, bis 2026 heisst bis 2026-12-31.
    """
    date_from = _date_bound(von, end=False)
    date_to = _date_bound(bis, end=True)
    if date_from and date_to and date_from > date_to:
        raise DiscoveryError(f"von {date_from} liegt nach bis {date_to}")
    return date_from, date_to


def parse_listing_date(text: Optional[str], today: Optional[date] = None) -> Optional[str]:
    """
    Liest das Kurzdatum der Listenseiten, etwa "19 Mär 26", als ISO Datum.

    Hikr kuerzt das Jahr auf zwei Stellen. Ein Jahr, das in der Zukunft
    laege, gehoert ins vorige Jahrhundert, aus "95" wird also 1995.
    """
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,2})\.?\s+([a-z]+)\.?\s+(\d{2}|\d{4})", _key(text))
    if not match:
        return None

    day, month_name, year = match.groups()
    month = MONTHS_SHORT.get(month_name)
    if month is None:
        return None

    year_number = int(year)
    if len(year) == 2:
        current = (today or date.today()).year
        year_number += 2000
        if year_number > current + 1:
            year_number -= 100

    try:
        return date(year_number, month, int(day)).isoformat()
    except ValueError:
        return None


def parse_listing(html: str, region_id: int, code: str, current_skip: int = 0) -> ListingPage:
    """
    Liest eine Listenseite. Jeder Bericht steht in einem div.content-list und
    ist zweimal verlinkt, ueber das Vorschaubild und ueber den Titel. Der
    Titellink zaehlt, doppelte URLs fallen weg.

    Die naechste Seite ist der Blaetterlink mit skip = current_skip + 10. Er
    wird ueber die Zahl gefunden statt ueber die Beschriftung "Vor", damit
    ein Link zurueck nie als naechste Seite gilt. Gefolgt wird nur Links, die
    exakt zu derselben Region und Kategorie gehoeren.
    """
    soup = BeautifulSoup(html, "lxml")

    entries: list[ListingEntry] = []
    seen: set[str] = set()
    for item in soup.select("div.content-list"):
        link = item.select_one("strong a[href]")
        if link is None:
            continue
        url = urljoin(BASE_URL + "/", link["href"].strip())
        if not POST_URL.match(url) or url in seen:
            continue
        seen.add(url)

        date_element = item.find(attrs={"title": "Tour Datum"})
        tour_date = (
            parse_listing_date(date_element.get_text(" ", strip=True))
            if date_element is not None
            else None
        )
        entries.append(ListingEntry(url, tour_date))

    navigator = soup.select_one("div.navigator")
    next_url = None
    if navigator is not None:
        pattern = re.compile(
            rf"^https://www\.hikr\.org/region{region_id}/{re.escape(code)}/\?skip=(\d+)&?$"
        )
        for anchor in navigator.find_all("a", href=True):
            candidate = urljoin(BASE_URL + "/", anchor["href"].strip())
            match = pattern.match(candidate)
            if match and int(match.group(1)) == current_skip + PAGE_SIZE:
                next_url = candidate
                break

    return ListingPage(entries, next_url, navigator is not None)


class HikrDiscovery:
    """
    Findet Tourenberichte auf Hikr ueber die Listen je Region und Kategorie.

    Laeuft nur mit einem gedrosselten Downloader, siehe
    build_polite_downloader. Pausen, robots.txt und Wiederholungen regelt
    damit derselbe Mechanismus wie beim Laden der Touren. Die Discovery
    liefert nur URLs, geladen und gespeichert wird woanders.

    Den Monatsfilter von Hikr (date_year_month) sperrt robots.txt. Ein
    Datumsbereich wird deshalb aus den normalen Listen gelesen: Sie sind
    nach Tourdatum absteigend sortiert, und jeder Eintrag zeigt sein Datum.
    """

    def __init__(self, downloader: Downloader, max_pages: int = MAX_PAGES_PER_CALL) -> None:
        if getattr(downloader, "limiter", None) is None:
            raise DiscoveryError(
                "Discovery braucht einen gedrosselten Downloader, siehe build_polite_downloader"
            )
        if (
            isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or not 1 <= max_pages <= MAX_PAGES_PER_CALL
        ):
            raise DiscoveryError(
                f"max_pages muss zwischen 1 und {MAX_PAGES_PER_CALL} liegen, war {max_pages!r}"
            )
        self.downloader = downloader
        self.max_pages = max_pages

    @staticmethod
    def listing_url(region_id: int, code: str, skip: int = 0) -> str:
        url = f"{BASE_URL}/region{region_id}/{code}/"
        return f"{url}?skip={skip}" if skip else url

    def find_urls(
        self,
        region: int | str,
        kategorie: str = "tour",
        max_results: int = DEFAULT_MAX_RESULTS,
        von: object = None,
        bis: object = None,
        is_known: Optional[Callable[[str], bool]] = None,
    ) -> list[str]:
        """Kurzform von discover, liefert nur die URLs."""
        return self.discover(
            region, kategorie, max_results, von=von, bis=bis, is_known=is_known
        ).urls

    def discover(
        self,
        region: int | str,
        kategorie: str = "tour",
        max_results: int = DEFAULT_MAX_RESULTS,
        von: object = None,
        bis: object = None,
        is_known: Optional[Callable[[str], bool]] = None,
        start_skip: int = 0,
        stop_at_known_page: bool = False,
    ) -> DiscoveryResult:
        """
        Blaettert durch die Liste und sammelt bis zu max_results URLs.

        Alle Kriterien werden geprueft, bevor die erste Anfrage rausgeht.
        Bekannte URLs (is_known) werden uebersprungen und zaehlen nicht mit.
        Einträge ausserhalb des Datumsbereichs zaehlen ebenfalls nicht.

        Schluss ist, sobald genug URLs da sind, ein Eintrag aelter als von
        auftaucht, die Liste endet oder max_pages Seiten gelesen sind. Mit
        stop_at_known_page endet der Lauf zudem an der ersten Seite, deren
        passende Eintraege alle schon bekannt sind. Das dient dem Nachsehen
        nach neuen Berichten in einer bereits vollstaendig durchsuchten Liste.
        """
        validate_max_results(max_results)
        region_id = resolve_region(region)
        code = resolve_category(kategorie)
        date_from, date_to = date_bounds(von, bis)
        if isinstance(start_skip, bool) or not isinstance(start_skip, int) or start_skip < 0:
            raise DiscoveryError(f"start_skip muss eine Zahl ab 0 sein, war {start_skip!r}")

        skip = start_skip - start_skip % PAGE_SIZE
        result = DiscoveryResult(region_id, code, date_from, date_to, resume_skip=skip)
        use_dates = date_from is not None or date_to is not None
        seen: set[str] = set()
        url = self.listing_url(region_id, code, skip)

        while result.pages_read < self.max_pages:
            html = self.downloader.fetch_html(url)
            result.pages_read += 1
            page = parse_listing(html, region_id, code, skip)
            self._check_page(page, url, use_dates)
            result.resume_skip = skip

            in_range = 0
            new = 0
            stop = False
            for entry in page.entries:
                if entry.url in seen:
                    continue
                seen.add(entry.url)

                if use_dates:
                    if entry.tour_date is None:
                        continue
                    if date_to is not None and entry.tour_date > date_to:
                        continue
                    if date_from is not None and entry.tour_date < date_from:
                        # Absteigend sortiert: alles Folgende ist noch aelter.
                        result.completed = True
                        stop = True
                        break

                in_range += 1
                if is_known is not None and is_known(entry.url):
                    continue

                result.found.append(entry)
                new += 1
                if len(result.found) >= max_results:
                    stop = True
                    break

            if stop:
                break
            if stop_at_known_page and in_range and not new:
                result.completed = True
                break
            if page.next_url is None:
                result.completed = True
                break

            url = page.next_url
            skip += PAGE_SIZE
            result.resume_skip = skip

        return result

    @staticmethod
    def _check_page(page: ListingPage, url: str, use_dates: bool) -> None:
        """
        Waechter gegen eine geaenderte Seitenstruktur. Ohne ihn lieferte eine
        umgebaute Seite still eine leere Liste oder einen falschen Bereich.
        """
        if page.has_navigator and not page.entries:
            raise DiscoveryError(
                f"{url} hat einen Blaetterblock, aber keine erkennbaren Eintraege. "
                f"Hat sich die Seitenstruktur geaendert?"
            )
        if use_dates:
            dates = [entry.tour_date for entry in page.entries if entry.tour_date]
            if any(later > earlier for earlier, later in zip(dates, dates[1:])):
                raise DiscoveryError(
                    f"{url} ist nicht absteigend nach Tourdatum sortiert. Ein "
                    f"Datumsbereich liesse sich so nicht verlaesslich lesen"
                )
