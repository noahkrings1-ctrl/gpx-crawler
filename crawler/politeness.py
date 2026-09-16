import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse


# Untergrenze fuer die Pause zwischen zwei Anfragen an dieselbe Domain.
# Kein Parameter kann sie unterschreiten.
MIN_DELAY_SECONDS = 2.0

# Netzfehler und die Serverfehler 502, 503 und 504 werden hoechstens so oft
# wiederholt, mit diesen Wartezeiten davor.
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = (15.0, 60.0)
RETRYABLE_STATUS = frozenset({502, 503, 504})

# Ein Retry-After bis zu dieser Laenge wird einmal abgewartet. Verlangt der
# Server mehr, endet der Lauf.
MAX_RETRY_AFTER_SECONDS = 300.0

# So viele Fehlschlaege hintereinander beenden einen Lauf.
MAX_CONSECUTIVE_FAILURES = 3


def domain_key(url: str) -> str:
    """
    Fasst Subdomains zu einer Domain zusammen, aus www.hikr.org und
    f.hikr.org wird hikr.org. Beide gehoeren demselben Betreiber. Ohne das
    folgte der GPX Download ohne Pause direkt auf die Tourseite.
    """
    host = (urlparse(url).hostname or "").lower()
    parts = [part for part in host.split(".") if part]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """
    Liest Retry-After als Sekundenzahl. Die zweite erlaubte Form, ein Datum,
    gilt als unbekannt. Lieber aufhoeren als eine Wartezeit raten.
    """
    if value is None:
        return None
    text = str(value).strip()
    return float(text) if text.isdigit() else None


def is_challenge(headers: Mapping[str, str]) -> bool:
    """Cloudflare kennzeichnet eine Pruefseite mit cf-mitigated: challenge."""
    return any(
        name.lower() == "cf-mitigated" and str(value).strip().lower() == "challenge"
        for name, value in headers.items()
    )


class RateLimiter:
    """
    Haelt eine Mindestpause zwischen zwei Anfragen an dieselbe Domain ein.

    Gemessen wird vom Beginn der letzten Anfrage an. Uhr und Schlaf lassen
    sich uebergeben, damit Tests die Pausen pruefen koennen, ohne zu warten.
    """

    def __init__(
        self,
        min_interval: float = MIN_DELAY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval < MIN_DELAY_SECONDS:
            raise ValueError(
                f"Die Pause darf {MIN_DELAY_SECONDS} Sekunden nicht unterschreiten, "
                f"verlangt waren {min_interval}"
            )
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_start: dict[str, float] = {}

    def wait(self, url: str, crawl_delay: Optional[float] = None) -> float:
        """
        Wartet vor einer Anfrage so lange wie noetig und liefert die
        Wartezeit. Ein Crawl-delay aus robots.txt gilt, wenn er laenger ist.
        """
        interval = max(self.min_interval, crawl_delay or 0.0)
        key = domain_key(url)
        waited = 0.0

        last = self._last_start.get(key)
        if last is not None:
            remaining = interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
                waited = remaining

        self._last_start[key] = self._clock()
        return waited

    def pause(self, seconds: float) -> None:
        """Zusaetzliche Wartezeit, etwa vor einer Wiederholung."""
        if seconds > 0:
            self._sleep(seconds)


@dataclass(frozen=True)
class RetryPolicy:
    """Wann und wie oft eine Anfrage wiederholt werden darf."""

    max_retries: int = MAX_RETRIES
    backoff_seconds: tuple[float, ...] = RETRY_BACKOFF_SECONDS
    max_retry_after_seconds: float = MAX_RETRY_AFTER_SECONDS

    def backoff(self, attempt: int) -> float:
        """Wartezeit vor Wiederholung Nummer attempt, gezaehlt ab 1."""
        index = min(max(attempt, 1), len(self.backoff_seconds)) - 1
        return self.backoff_seconds[index]


class RobotsPolicy:
    """
    Liest robots.txt je Host einmal pro Lauf und prueft jede URL davor.

    Geladen wird erst, wenn wirklich eine Anfrage an den Host ansteht. Ein
    Lauf, der alles aus dem lokalen Speicher bedient, fragt also auch
    robots.txt nicht ab.

    Fehlt die Datei (404), ist alles erlaubt. Ist sie nicht erreichbar
    (5xx oder Netzfehler) oder selbst gesperrt (401, 403), wird der Host
    als gesperrt behandelt. Unbekannte Regeln heissen: nicht crawlen.
    """

    def __init__(self, user_agent: str, fetch: Callable[[str], tuple[int, str]]) -> None:
        self.user_agent = user_agent
        self._fetch = fetch
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        return self._parser_for(url).can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> Optional[float]:
        delay = self._parser_for(url).crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None

    def _parser_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin + "/robots.txt")
        return self._parsers[origin]

    def _load(self, robots_url: str) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser(robots_url)
        status, text = self._fetch(robots_url)

        if status == 200:
            parser.parse(text.splitlines())
        elif status in (401, 403):
            parser.disallow_all = True
        elif 400 <= status < 500:
            parser.allow_all = True
        else:
            # 5xx oder Status 0 fuer einen Netzfehler: Regeln unbekannt.
            parser.disallow_all = True
        return parser
