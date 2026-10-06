import socket
from pathlib import Path

import pytest

from storage import TourStore
from storage.tour_store import DEFAULT_DB_PATH


@pytest.fixture(autouse=True)
def echte_datenbank_bleibt_unberuehrt(monkeypatch):
    """
    Waechter fuer die echte Ablage unter data/tours.sqlite3.

    TourStore laesst sich ohne Pfadargument anlegen und zeigt dann auf die
    echte Datei. Ein Test, der das versehentlich tut, wuerde in die
    Produktivdaten schreiben, ohne dass es jemand merkt.

    Geprueft wird der Pfad beim Anlegen, nicht der Zeitstempel der Datei.
    Ein Vergleich vor und nach der Suite schlug auch dann an, wenn nebenher
    ein echter Lauf schrieb: Die Datei gehoert dem Crawler, und der darf
    laufen, waehrend die Tests laufen.
    """
    echtes_init = TourStore.__init__

    def nur_mit_eigenem_pfad(self, db_path=DEFAULT_DB_PATH, *args, **kwargs):
        if Path(db_path) == Path(DEFAULT_DB_PATH):
            raise AssertionError(
                f"Ein Test oeffnet {DEFAULT_DB_PATH}. Tests muessen tmp_path "
                f'oder ":memory:" benutzen, nie den Standardpfad.'
            )
        echtes_init(self, db_path, *args, **kwargs)

    monkeypatch.setattr(TourStore, "__init__", nur_mit_eigenem_pfad)


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
