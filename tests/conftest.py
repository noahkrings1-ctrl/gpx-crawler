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
