# Anleitung

Spickzettel fuer den taeglichen Gebrauch: Touren holen, Touren suchen, in der
Ablage nachsehen. Alle Befehle laufen im Projektverzeichnis.

Entweder mit vollem Pfad zum Interpreter:

    .\venv\Scripts\python.exe main.py --help

Oder einmal die Umgebung aktivieren, danach genuegt `python`:

    venv\Scripts\activate
    python main.py --help

In dieser Anleitung steht immer `python`. Ohne aktivierte Umgebung davor
`.\venv\Scripts\python.exe` schreiben.

## 1 Einrichten

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    pytest

## 2 Touren holen

### Die feste Liste

Ohne Optionen wird die fest hinterlegte Liste `TOUR_URLS` in `main.py`
abgearbeitet. Gut zum Ausprobieren, holt aber nichts Neues.

    python main.py

### Discovery

Gesucht wird nur mit `--discover`, nie von allein. `--region` und
`--kategorie` sind dabei Pflicht.

    python main.py --discover --region Uri --kategorie skitouren --max 50
    python main.py --discover --region 44 --kategorie wandern --von 2021 --bis 2026 --schwierigkeit T4 T5 T6 --max 100
    python main.py --discover --region Uri --kategorie hochtouren --tourtyp ski-hochtour --schwierigkeit WS ZS
    python main.py --discover --region 146 --kategorie ski --nur-urls
    python main.py --discover --region Wallis --kategorie wandern --nur-mit-gpx --max 50

| Option | Bedeutung |
| --- | --- |
| `--discover` | Schaltet die Suche ein. Ohne sie laeuft die feste Liste |
| `--region` | Name wie Uri, Glarus, Graubünden oder die ID aus der URL der Regionsseite, etwa 146 aus `region146.html` |
| `--kategorie` | wandern, hochtouren, skitouren, klettern, schneeschuhe, klettersteig, eisklettern, alle. Die Codes ped, alp, ski, esc, raq, via, eis, tour gehen auch |
| `--von` / `--bis` | Tourdatum als Jahr `2021` oder als Datum `2021-06-01`. Beide Enden zaehlen mit |
| `--schwierigkeit` | Eine oder mehrere Stufen, etwa `T4 T5 T6` oder `WS ZS`. Mehrere gelten als oder |
| `--tourtyp` | Nur Touren mit Hochtourennote: `ski-hochtour`, `alpinwandern-hochtour` oder `hochtour` |
| `--max` | Hoechstens so viele neue Touren je Lauf. Standard 20, Obergrenze 100 |
| `--nur-urls` | Nur suchen und vormerken, keine Tour laden |
| `--nur-mit-gpx` | Nur Touren mit GPX Datei ablegen. Touren ohne werden vermerkt und nie erneut angefragt |
| `--datenbank` | Andere Ablage als `data\tours.sqlite3` |

### Wie ein Lauf ablaeuft

Ueblicher Ablauf in drei Schritten:

    python main.py --discover --region Glarus --kategorie wandern --von 2021 --bis 2026 --schwierigkeit T4 T5 T6 --max 100 --nur-urls
    python query.py --limit 5
    python main.py --discover --region Glarus --kategorie wandern --von 2021 --bis 2026 --schwierigkeit T4 T5 T6 --max 100

Erst nur die URLs sammeln, dann denselben Befehl ohne `--nur-urls` starten. Er
arbeitet die vorgemerkten URLs ab, bevor er weitersucht.

Vier Dinge, die den Ablauf erklaeren:

- **Ein Lauf liest hoechstens 20 Listenseiten**, also 200 Eintraege. Endet die
  Meldung mit `Suchbereich weiter ab skip=200`, war das nicht alles. Dann
  denselben Befehl nochmal starten, er macht dort weiter. Erst
  `vollstaendig durchsucht` heisst fertig.
- **Jede Kombination ist eine eigene Suche**, mit eigenem Suchstand: Region,
  Kategorie, Schwierigkeit, Tourtyp und die Datumsspanne. Aendert man die
  Spanne, faengt die Suche wieder oben an. Also dieselbe Spanne beibehalten,
  bis sie vollstaendig ist.
- **Bekannte URLs werden nie erneut angefragt.** Ein zweiter Lauf kostet also
  nichts ausser den Listenseiten.
- **`--nur-mit-gpx` spart keine Anfragen.** Ob eine Tour eine GPX Datei hat,
  steht erst auf der Tourseite. Sie wird geladen und dann verworfen, wenn
  keine Datei dabei ist. Gespart wird der Eintrag in der Datenbank.
- **Zwischen zwei Anfragen liegen mindestens zwei Sekunden.** Ein Lauf ueber
  20 Listenseiten dauert rund eine Minute, 100 Touren entsprechend laenger.

### Rueckgabewerte

| Wert | Bedeutung |
| --- | --- |
| 0 | Erfolg |
| 1 | Fehler beim Laden oder in der Ablage |
| 2 | Ungueltige Kriterien, etwa eine unbekannte Kategorie |
| 3 | Hikr hat den Zugriff verweigert |

## 3 Touren suchen

`query.py` durchsucht nur die lokale Ablage und geht nie ins Netz. Ohne Filter
kommt alles.

    python query.py
    python query.py --region Uri --sportart Skitour --von 2024
    python query.py --sportart Wandern --schwierigkeit T4 T5 T6 --limit 20
    python query.py --tourtyp ski-hochtour --schwierigkeit ZS
    python query.py --text biwak
    python query.py --region Wallis --mit-gpx
    python query.py --max-aufstieg 1200 --max-dauer 5:30
    python query.py --sortierung distance_km --absteigend --limit 10

| Option | Bedeutung |
| --- | --- |
| `--region` | Land, Hauptregion oder Gebiet. Umlaute duerfen ausgeschrieben werden, Graubuenden findet Graubünden |
| `--sportart` | Wandern, Hochtour, Klettern, Skitour |
| `--schwierigkeit` | Eine oder mehrere Stufen, auf jeder Skala |
| `--tourtyp` | ski-hochtour, alpinwandern-hochtour, hochtour |
| `--min-aufstieg` / `--max-aufstieg` | Aufstieg in Metern |
| `--max-dauer` | Gehzeit hoechstens, als `5:30` oder als Minutenzahl |
| `--von` / `--bis` | Tourdatum, als Jahr oder als Datum |
| `--text` | Stichwort in Titel und Berichtstext |
| `--mit-gpx` | Nur Touren mit heruntergeladener GPX Datei |
| `--sortierung` | date_iso (Standard), title, distance_km, elevation_gain_m, elevation_loss_m, time_required_min, sport, region_country, region_main, region_leaf |
| `--absteigend` | Groesste Werte zuerst |
| `--limit` | Hoechstens so viele Zeilen |

Zur Schwierigkeit: verglichen wird die Stufe genau. `ZS` trifft ZS-, ZS und
ZS+, aber nicht WS. `T4` trifft nicht T5. Wer eine Spanne will, zaehlt die
Stufen auf: `--schwierigkeit T4 T5 T6`.

Die Skalen: `T1` bis `T6` beim Wandern, `L` bis `EX` bei Hochtouren und
Skitouren, roemische Zahlen beim Klettern, `WT1` bis `WT6` bei
Schneeschuhtouren.

Schneeschuhtouren holst du so:

    python main.py --discover --region 146 --kategorie schneeschuhe --max 100
    python query.py --sportart Schneeschuhtour --schwierigkeit WT3 WT4

## 4 In der Ablage nachsehen

Die Ablage liegt in `data\tours.sqlite3`, mit drei Tabellen:

| Tabelle | Inhalt |
| --- | --- |
| `tours` | Die Touren selbst, eine Zeile je Bericht |
| `discovered_urls` | Jede gefundene URL mit Status `neu`, `gespeichert`, `fehlgeschlagen` oder `ohne_gpx` |
| `discovery_progress` | Wo jede Suche steht: `resume_skip` und `completed` |

Ein Kommandozeilenwerkzeug fuer SQLite ist nicht installiert. Fuer einen Blick
in die Tabellen gibt es zwei Wege: einen Python Einzeiler oder eine
grafische Oberflaeche wie DB Browser for SQLite, dort einfach die Datei
oeffnen.

Muster fuer die Einzeiler, mit doppelten Anfuehrungszeichen aussen und
einfachen innen. Werte gehoeren als `?` in die Abfrage, sonst beendet Python
den Text an der falschen Stelle:

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); [print(r) for r in con.execute('SELECT ... FROM ... WHERE spalte = ?', ('wert',))]"

Wo steht welche Suche, was ist offen:

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); [print(r) for r in con.execute('SELECT region_id, category, date_from, date_to, resume_skip, completed FROM discovery_progress ORDER BY region_id, category')]"

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); [print(r) for r in con.execute('SELECT region_id, category, status, COUNT(*) FROM discovered_urls GROUP BY 1, 2, 3 ORDER BY 1, 2')]"

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); [print(r) for r in con.execute('SELECT url, tour_date FROM discovered_urls WHERE status = ? ORDER BY tour_date DESC', ('neu',))]"

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); [print(r) for r in con.execute('SELECT url, tour_date FROM discovered_urls WHERE status = ?', ('fehlgeschlagen',))]"

Was liegt drin:

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); print(con.execute('SELECT COUNT(*), MIN(date_iso), MAX(date_iso) FROM tours').fetchone())"

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); [print(r) for r in con.execute('SELECT substr(date_iso, 1, 4) AS jahr, COUNT(*) FROM tours GROUP BY jahr ORDER BY jahr')]"

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); [print(r) for r in con.execute('SELECT region_main, sport, COUNT(*) FROM tours GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10')]"

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); print(con.execute('SELECT COUNT(gpx_path), COUNT(*) FROM tours').fetchone())"

Eine einzelne Tour mit allen Feldern ausser dem Berichtstext:

    python -c "import sqlite3; con = sqlite3.connect('data/tours.sqlite3'); con.row_factory = sqlite3.Row; r = con.execute('SELECT * FROM tours ORDER BY date_iso DESC LIMIT 1').fetchone(); [print(k, '=', r[k]) for k in r.keys() if k != 'main_text']"

Die Spalten von `tours`: source_url, title, region, region_country,
region_main, region_area, region_leaf, date, date_iso, sport,
difficulty_hiking, difficulty_alpine, difficulty_climbing, difficulty_ski,
elevation_gain_m, elevation_loss_m, time_required, time_required_min,
duration_days, distance_km, language, gpx_url, gpx_path, main_text,
created_at, updated_at.

Aus Python heraus geht es auch ohne SQL:

    python -c "from storage.tour_store import TourStore; store = TourStore('data/tours.sqlite3'); store.connect(); print(len(store.find_tours(region='Uri', sport='Skitour')))"

## 5 Dateien auf der Platte

| Ort | Inhalt |
| --- | --- |
| `data\html` | Die heruntergeladenen Tourseiten, nach Tour-ID benannt |
| `data\gpx` | Die GPX Dateien, benannt nach Datum und Titel |
| `data\tours.sqlite3` | Die Ablage |

    (Get-ChildItem data\gpx\*.gpx).Count
    (Get-ChildItem data\html\*.html).Count
    Get-ChildItem data\gpx | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name, Length

Eine einzelne GPX Datei nachrechnen, ohne Netz:

    python -c "from parsers import GpxParser; print(GpxParser().parse_local_gpx('data/gpx/DATEINAME.gpx'))"

## 6 Tests

    pytest
    pytest -q
    pytest tests\test_discovery.py -v
    pytest -k gpx

Die Tests gehen nie ins Netz und legen keine Datei im Projekt an.

## 7 Noah's Tourenportal

Die gesammelten Touren lassen sich auch mit der Oberflaeche durchsuchen,
statt mit query.py:

    C:\Dev\tourenportal\venv\Scripts\python.exe C:\Dev\tourenportal\app.py

Das Portal oeffnet `data\tours.sqlite3` **nur lesend** und fuehrt sein
eigenes Tourenbuch in einem eigenen Projekt. Ein Crawl kann dem Tourenbuch
also nichts anhaben, und das Portal dieser Ablage nichts. Die Anleitung
dazu steht in `C:\Dev\tourenportal\ANLEITUNG.md`.
