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
- main.py laeuft durch die ganze Kette: HTML laden, parsen, GPX laden,
  Distanz berechnen, Metadaten ausgeben
- Tests in tests/ laufen gruen (22), Netzwerkzugriffe sind im Test ueber
  monkeypatch ersetzt, GPX Dateien werden als Fixture geschrieben
- pyproject.toml konfiguriert pytest mit pythonpath und testpaths
- Erfolgreich getestet an einer echten Hikr Tour (Sunnig Wichel)
- Distanz stammt aus der GPX Datei, nicht aus dem HTML

## Architektur
- crawler/downloader.py     Klasse Downloader mit DownloadError
- parsers/hikr_parser.py    Klasse HikrParser mit LABEL_MAP
- parsers/gpx_parser.py     Klasse GpxParser mit GpxParseError
- data/html                 Lokale HTML Ablage, per gitignore ausgeschlossen
- data/gpx                  Lokale GPX Ablage, per gitignore ausgeschlossen
- tests                     pytest Tests
- main.py                   Einstiegspunkt fuer manuelle Laeufe

## Konventionen
- Python 3.14 im venv unter Windows 11
- requests, BeautifulSoup und gpxpy als Kernbibliotheken
- pytest fuer Tests, konfiguriert ueber pyproject.toml
- Kleine, haeufige Commits mit klaren Botschaften auf Deutsch
- Umlaute korrekt, keine unnoetigen Sonderzeichen
- Klassen basierter Aufbau, Type Hints wo sinnvoll
- Fehlerbehandlung ueber eigene Exceptions wie DownloadError

## Danach geplant
- Orchestrator in main.py fuer Listen von URLs
- Erweiterung des Parsers um Extraktion des Beschreibungstexts (main_text)
- Lokale SQLite Datenbank als zentrale Ablage aller Tourmetadaten
- Filterfunktionen ueber Sportart, Region, Schwierigkeit und Dauer
- Kommandozeilen Interface fuer Datenbankabfragen
- Spaeter zweiter Parser fuer Gipfelbuch

## Langfristige Vision

Das Projekt soll am Ende nicht nur Metadaten sammeln, sondern eine
durchsuchbare persoenliche Tourdatenbank sein.

### Datenbank
- SQLite als lokale Datei, keine Serverabhaengigkeit
- Tabelle mit strukturierten Metadaten (Titel, Region, Datum, Schwierigkeit,
  Dauer, Aufstieg, Abstieg, Distanz, Sportart, Sprache, GPX Pfad, Quelle URL)
- Optional SQLAlchemy als ORM, um SQL nicht direkt schreiben zu muessen
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