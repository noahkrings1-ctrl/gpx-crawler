# GPX Crawler Projekt

## Ziel
Python Crawler, der Tourenberichte auf Hikr.org analysiert
und GPX Dateien samt Metadaten extrahiert. Spaeter erweiterbar um weitere Websites wie Gipfelbuch.
Aufbau einer Hochtouren Metadaten Datenbank, mit der gezielt Regionen gefiltert und gesucht werden können.

## Aktueller Stand (September 2026)

Die Kette steht: Hikr URL -> Metadaten -> GPX -> Distanz -> SQLite -> Suche
mit query.py. Die Ablage enthaelt zwoelf echte Touren, acht davon mit GPX
Datei. 96 Tests laufen gruen.

### Crawler
- Downloader mit realistischen Browser Headern und brotli Support
- download_gpx legt GPX Dateien nach data/gpx ab, benannt nach Datum und
  Titel, z.B. 2026-07-12-sunnig-wichel-via-nordgrat.gpx. Gespeichert wird als
  Bytes, eine Pruefung auf das gpx Wurzelelement faengt HTML Fehlerseiten ab
- main.py arbeitet die Liste TOUR_URLS ab, zwoelf echte Touren von T1 bis
  Hochtour ZS-. Ein Fehlschlag bricht den Lauf nicht ab, zwischen zwei
  Aufrufen liegen 1.5 Sekunden
- Vorhandenes HTML wird wiederverwendet (REUSE_LOCAL_HTML), GPX Dateien werden
  bei jedem Lauf neu geladen

### Parser
- HikrParser liest die Tabelle fiche_rando ueber LABEL_MAP, nur deutsche Labels
- Rohfelder bleiben erhalten, daneben stehen normalisierte Felder: date_iso,
  elevation_gain_m, elevation_loss_m, time_required_min, duration_days
- Der Zeitbedarf hat zwei Formate. 5:00 wird zu 300 Minuten, 6 Tage landet in
  duration_days. Eine Umrechnung in Minuten waere irrefuehrend
- Die Region ist zerlegt in region_country, region_main und region_area, dazu
  region_leaf. region_main ist in der Schweiz der Kanton, in Oesterreich eine
  Gebirgsgruppe, daher der neutrale Name
- sport wird aus der Schwierigkeitsskala abgeleitet: Hochtour vor Wandern vor
  Klettern. Eine UIAA Note neben einer T Note ist nur eine Kletterstelle
- GpxParser berechnet die Distanz horizontal in Kilometern mit gpxpy. Routen
  ohne Track werden mitgezaehlt, ohne verwertbare Punkte gibt es None statt 0.0

### Ablage
- TourStore in storage/tour_store.py, Datei data/tours.sqlite3 mit 25 Spalten.
  Schluessel ist source_url, upsert statt Duplikat, created_at bleibt erhalten
- find_tours filtert nach region, sport, difficulty, min_elevation_gain,
  max_elevation_gain und max_duration_minutes, dazu order_by, descending und
  limit. Fehlender Filter heisst kein Filter
- region und difficulty pruefen mehrere Spalten mit OR. Verglichen wird als
  Teiltext, beide Seiten laufen vorher durch normalise (klein geschrieben,
  Umlaute ausgeschrieben), damit "Österreich" und "Oesterreich" dasselbe finden
- difficulty nimmt einen String oder eine Liste, mehrere Werte gelten als oder.
  Leere und doppelte Begriffe fallen heraus
- Werte gehen nur als Platzhalter ins SQL, die Sortierspalte ist ueber die
  Weissliste SORTABLE_COLUMNS abgesichert
- Leere Felder stehen beim Sortieren in beiden Richtungen am Ende
- Mehrtaegige Touren haben time_required_min NULL und fallen bei einem Filter
  auf die Gehzeit heraus, das ist gewollt

### Suche
- query.py uebersetzt Kommandozeilenargumente in find_tours und gibt eine
  Tabelle aus. Fehlt die Datenbank, gibt es einen Hinweis und Rueckgabewert 1
- --max-dauer versteht 5:30 und 330
- --schwierigkeit nimmt mehrere Werte (nargs + und action extend). Ein zweites
  --schwierigkeit ergaenzt, statt den ersten Wert still zu ueberschreiben

### Tests
- 96 Tests: tour_store 36, query 26, downloader 12, hikr_parser 10,
  gpx_parser 7, main 5
- Keine Netzwerkzugriffe, requests.get wird ueber monkeypatch ersetzt
- tests/conftest.py wacht darueber, dass kein Test data/tours.sqlite3 anfasst.
  Schreibende Tests nutzen tmp_path, reine Abfragetests eine Datenbank im
  Arbeitsspeicher
- pyproject.toml konfiguriert pytest mit pythonpath und testpaths

## Bekannte Grenzen
- Die Schwierigkeit ist ein Teiltextfilter, kein Bereichsfilter. II trifft
  auch III, einzelne Buchstaben wie S oder L treffen fast alles
- Nur deutschsprachige Hikr Seiten, die Spalte language wird nicht befuellt
- Keine Schemamigration. CREATE TABLE IF NOT EXISTS ergaenzt keine Spalten in
  einer bestehenden Datei, neue Spalten brauchen eine neue Datenbankdatei

## Architektur
- crawler/downloader.py     Klasse Downloader mit DownloadError
- parsers/hikr_parser.py    Klasse HikrParser mit LABEL_MAP
- parsers/gpx_parser.py     Klasse GpxParser mit GpxParseError
- storage/tour_store.py     Klasse TourStore mit TourStoreError, einziges SQL
- data/html                 Lokale HTML Ablage, per gitignore ausgeschlossen
- data/gpx                  Lokale GPX Ablage, per gitignore ausgeschlossen
- data/tours.sqlite3        Tourdatenbank, per gitignore ausgeschlossen
- tests                     pytest Tests, conftest.py mit Waechter
- main.py                   Crawl Lauf ueber die Liste TOUR_URLS
- query.py                  Suchinterface mit Tabellenausgabe

## Konventionen
- Python 3.14 im venv unter Windows 11
- requests, BeautifulSoup und gpxpy als Kernbibliotheken, sqlite3 aus der
  Standardbibliothek fuer die Ablage, kein ORM
- pytest fuer Tests, konfiguriert ueber pyproject.toml
- Kleine, haeufige Commits mit klaren Botschaften auf Deutsch
- Umlaute korrekt, keine unnoetigen Sonderzeichen
- Klassen basierter Aufbau, Type Hints wo sinnvoll
- Fehlerbehandlung ueber eigene Exceptions wie DownloadError

## Hinweise fuer die Arbeit am Projekt
- Zeilenenden sind CRLF (core.autocrlf true). Neue Dateien ebenfalls mit CRLF
  schreiben, sonst erscheinen im Diff ganze Dateien als geaendert
- requirements.txt ist UTF-16, entstanden durch pip freeze unter PowerShell.
  pip liest das problemlos, beim Bearbeiten die Kodierung beibehalten
- Die Windows Konsole laeuft mit cp1252. Ausgaben mit Titeln und Regionen ueber
  sys.stdout.reconfigure(errors="replace") absichern
- Commits: Botschaft als Datei schreiben und mit git commit -F datei -- pfade
  committen. Heredocs in verketteten Shellbefehlen haben hier mehrfach alle
  Aenderungen in einen einzigen Commit gezogen

## Danach geplant
- Erweiterung des Parsers um Extraktion des Beschreibungstexts (main_text)
- Mehrsprachigkeit im Parser (de, fr, it, en)
- Spaeter Bereichsfilter fuer die Schwierigkeit, z.B. bis WS
- Spaeter zweiter Parser fuer Gipfelbuch

## Langfristige Vision

Das Projekt soll am Ende nicht nur Metadaten sammeln, sondern eine
durchsuchbare persoenliche Tourdatenbank sein.

### Datenbank
- SQLite als lokale Datei, keine Serverabhaengigkeit
- Tabelle mit strukturierten Metadaten (Titel, Region, Datum, Schwierigkeit,
  Dauer, Aufstieg, Abstieg, Distanz, Sportart, Sprache, GPX Pfad, Quelle URL)
- Kein ORM, sqlite3 aus der Standardbibliothek. Das gesamte SQL steht in
  storage/tour_store.py, ein Wechsel auf SQLAlchemy betraefe nur dieses
  Modul. Kein sqlite3.Error verlaesst die Ablage, alles wird zu
  TourStoreError
- Migration von JSON oder CSV zur Datenbank soll gut dokumentiert sein

### Tag System
- Schluesselwoerter aus dem Beschreibungstext extrahieren
- Beispiel Tags: bruechig, lohnenswert, ausgesetzt, familientauglich,
  einsam, ueberlaufen, technisch, konditionell, wetterabhaengig
- Startpunkt sind einfache Wortlisten pro Kategorie
- Spaeter Ausbau moeglich in Richtung NLP oder LLM basierte Klassifikation
- Tags werden pro Tour in einer verknuepften Tabelle abgelegt

### Filterung
- Kombinierbare Filter, z.B. "Skitour im Wallis, Schwierigkeit bis WS,
  Aufstieg unter 1500 m, mit Tag lohnenswert und ohne Tag ueberlaufen"
- Ausgabe als sortierte Liste im Terminal, spaeter evtl. als kleine Web UI
