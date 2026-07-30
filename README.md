# GPX Webcrawler

Ein Python Crawler, der Tourenberichte auf Hikr.org analysiert und
GPX Dateien samt Metadaten extrahiert.

## Zielarchitektur

- crawler   Download von Webseiten
- parsers   Website spezifische Extraktion
- data      Lokale Ablage von HTML, GPX und Exports
- tests     Testcode
- main.py   Orchestrierung

## Setup

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

## Status

Frühe Lernphase. Fokus auf requests und BeautifulSoup.
Website Fokus: Hikr.org mit rund 20 Beispieltouren.
