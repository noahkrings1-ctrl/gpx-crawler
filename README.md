# GPX Webcrawler

Ein Python Crawler, der Tourenberichte auf Hikr.org analysiert und
GPX Dateien samt Metadaten extrahiert.

## Roadmap

Die naechsten geplanten Ausbaustufen des Projekts.

### Kurzfristig
- GPX Download in den Ordner data/gpx
- Distanzberechnung aus GPX mit gpxpy
- Erweiterung des Parsers um Mehrsprachigkeit (de, fr, it, en)
- Testfixtures fuer verschiedene Tourkategorien und Sprachen

### Mittelfristig
- Lokale Datenbank (SQLite) als zentrale Ablage der Tourmetadaten
- Filterfunktionen ueber Sportart, Region, Schwierigkeit und Dauer
- Kommandozeilen Interface fuer die Datenbankabfrage

### Langfristig
- Schluesselwort Extraktion aus Tourbeschreibungen
- Automatische Tag Vergabe (z.B. bruechig, lohnenswert, ausgesetzt, familientauglich)
- Filterung nach Tags zusaetzlich zu den strukturierten Metadaten
- Zweiter Parser fuer weitere Websites wie Gipfelbuch

## Zielarchitektur

- crawler   Download von Webseiten
- parsers   Website spezifische Extraktion
- data      Lokale Ablage von HTML, GPX und Exports
- tests     Testcode
- main.py   Orchestrierung
- Verzeichnis erstellen in welchem Metadaten filterbar sind

## Setup

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

## Status

Frühe Lernphase. Fokus auf requests und BeautifulSoup.
Website Fokus: Hikr.org mit rund 20 Beispieltouren.
