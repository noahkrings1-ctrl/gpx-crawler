# GPX Crawler Projekt

## Ziel
Python Crawler, der Tourenberichte auf Hikr.org analysiert
und GPX Dateien samt Metadaten extrahiert. Spaeter erweiterbar um weitere Websites wie Gipfelbuch.
Aufbau einer Hochtouren Metadaten Datenbank mit der gezielt regionen 

## Aktueller Stand
- Downloader mit realistischen Browser Headern und brotli Support
- Downloader Methode download_gpx legt GPX Dateien nach data/gpx ab, benannt
  nach Datum und Tourtitel, z.B. 2026-07-12-sunnig-wichel-via-nordgrat.gpx
- HikrParser extrahiert Metadaten aus der Tabelle mit Klasse fiche_rando
- HikrParser liefert zusaetzlich date_iso, das normalisierte Tourdatum im
  Format 2026-07-12, das Rohfeld date bleibt daneben erhalten
- GpxParser berechnet die Distanz aus der GPX Datei mit gpxpy, horizontal
  in Kilometern, Routen ohne Track werden mitgezaehlt
- main.py arbeitet die Liste TOUR_URLS ab: HTML laden, parsen, GPX laden,
  Distanz berechnen, Uebersicht als Tabelle ausgeben
- TOUR_URLS enthaelt zwoelf echte Hikr Touren mit Bandbreite, von T1
  Wandern bis Hochtour ZS-, acht davon mit GPX Datei
- Ein Fehlschlag bricht den Lauf nicht ab, Ergebnisse und Fehler werden
  getrennt gesammelt, zwischen zwei Aufrufen liegt eine Pause
- HTML wird je Tour unter dem Namen aus der URL abgelegt und bei einem
  erneuten Lauf wiederverwendet, siehe REUSE_LOCAL_HTML
- HikrParser liefert die Zahlenfelder elevation_gain_m, elevation_loss_m,
  time_required_min und duration_days, dazu region_leaf und sport
- Zeitbedarf hat zwei Formate. 5:00 wird zu 300 Minuten, 6 Tage landet in
  duration_days. Eine Umrechnung in Minuten waere irrefuehrend
- TourStore legt die Metadaten in data/tours.sqlite3 ab, Schluessel ist
  die Quelle URL, ein zweiter Lauf aktualisiert statt zu verdoppeln
- HikrParser zerlegt die Regionskette in region_country, region_main und
  region_area. Die mittlere Stufe ist in der Schweiz der Kanton, in
  Oesterreich eine Gebirgsgruppe, daher der neutrale Name
- find_tours filtert nach Region, Sportart, Schwierigkeit, Aufstieg von
  bis und maximaler Gehzeit. Fehlender Filter heisst kein Filter
- Suchbegriffe und Spaltenwerte laufen durch normalise, damit
  Oesterreich und Oesterreich dasselbe finden. SQLite vergleicht bei
  LIKE sonst nur ASCII
- Mehrtaegige Touren haben time_required_min NULL und fallen bei einem
  Filter auf die Gehzeit heraus, das ist gewollt
- query.py ist das Suchinterface, uebersetzt Argumente in find_tours und
  gibt eine Tabelle aus. --max-dauer versteht 5:30 und 330
- Ein echter Lauf hat zwoelf Touren abgelegt, Filter ueber Sportart,
  Region, Aufstieg und Distanz funktionieren
- Tests in tests/ laufen gruen (84), Netzwerkzugriffe sind im Test ueber
  monkeypatch ersetzt, GPX Dateien werden als Fixture geschrieben
- pyproject.toml konfiguriert pytest mit pythonpath und testpaths
- Erfolgreich getestet an einer echten Hikr Tour (Sunnig Wichel)
- Distanz stammt aus der GPX Datei, nicht aus dem HTML

## Architektur
- crawler/downloader.py     Klasse Downloader mit DownloadError
- parsers/hikr_parser.py    Klasse HikrParser mit LABEL_MAP
- parsers/gpx_parser.py     Klasse GpxParser mit GpxParseError
- storage/tour_store.py     Klasse TourStore mit TourStoreError,
                            einziges SQL im Projekt
- data/html                 Lokale HTML Ablage, per gitignore ausgeschlossen
- data/gpx                  Lokale GPX Ablage, per gitignore ausgeschlossen
- tests                     pytest Tests
- main.py                   Einstiegspunkt fuer manuelle Laeufe
- query.py                  Suchinterface mit Tabellenausgabe

## Konventionen
- Python 3.14 im venv unter Windows 11
- requests, BeautifulSoup und gpxpy als Kernbibliotheken, sqlite3 aus der
  Standardbibliothek fuer die Ablage
- pytest fuer Tests, konfiguriert ueber pyproject.toml
- Kleine, haeufige Commits mit klaren Botschaften auf Deutsch
- Umlaute korrekt, keine unnoetigen Sonderzeichen
- Klassen basierter Aufbau, Type Hints wo sinnvoll
- Fehlerbehandlung ueber eigene Exceptions wie DownloadError

## Danach geplant
- Erweiterung des Parsers um Extraktion des Beschreibungstexts (main_text)
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