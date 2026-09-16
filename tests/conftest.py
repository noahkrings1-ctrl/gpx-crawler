import socket
from pathlib import Path

import pytest

from storage.tour_store import DEFAULT_DB_PATH


def _fingerprint(path: Path) -> tuple[bool, int, float]:
    """Existenz, Groesse und Zeitstempel einer Datei in einem Wert."""
    if not path.exists():
        return (False, 0, 0.0)
    stat = path.stat()
    return (True, stat.st_size, stat.st_mtime)


@pytest.fixture(autouse=True, scope="session")
def echte_datenbank_bleibt_unberuehrt():
    """
    Waechter fuer die echte Ablage unter data/tours.sqlite3.

    TourStore laesst sich ohne Pfadargument anlegen und zeigt dann auf die
    echte Datei. Ein Test, der das versehentlich tut, wuerde in die
    Produktivdaten schreiben, ohne dass es jemand merkt. Dieser Vergleich
    vor und nach der Suite faellt sofort auf.
    """
    before = _fingerprint(DEFAULT_DB_PATH)
    yield
    after = _fingerprint(DEFAULT_DB_PATH)

    assert after == before, (
        f"Ein Test hat {DEFAULT_DB_PATH} veraendert. Tests muessen tmp_path "
        f'oder ":memory:" benutzen, nie den Standardpfad.'
    )


@pytest.fixture(autouse=True)
def kein_netzwerk(monkeypatch):
    """
    Waechter gegen echte Netzverbindungen.

    Tests ersetzen requests.get oder bekommen einen Fake Downloader. Faellt
    das in einem Test einmal weg, ginge die Anfrage sonst still an Hikr.
    So schlaegt der Test stattdessen laut fehl.
    """

    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "Ein Test wollte eine echte Netzverbindung aufbauen. Tests laufen ohne "
            "Netz, bitte requests.get ersetzen oder einen Fake Downloader verwenden."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class FakeClock:
    """
    Uhr, die nur beim Schlafen vorrueckt. Tests pruefen damit Pausen und
    Wartezeiten, ohne wirklich zu warten.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()
