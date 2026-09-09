# GPX Webcrawler

Ein Python Crawler, der Tourenberichte auf Hikr.org analysiert und
GPX Dateien samt Metadaten extrahiert. Ziel ist eine durchsuchbare
persoenliche Tourdatenbank.

## Zwischenstand September 2026

Die Kette steht und laeuft gegen die echte Website. Eine Liste von Hikr URLs
wird abgearbeitet, jede Tour gelesen, die verlinkte GPX Datei geladen und
vermessen, das Ergebnis als Tabelle ausgegeben.

Letzter Lauf ueber zwoelf echte Touren: 12 gelesen, 8 mit GPX Datei,
0 Fehlschlaege.

    Datum         Distanz  Schwierigkeit          Titel
    2023-06-18   92.98 km  T2 - Bergwandern       Meraner Hoehenweg
    2026-08-01   16.83 km  T3 - anspruchsvolles B Passo Bornengo
    2026-08-12   13.08 km  T5 - anspruchsvolles A Laeged und Schaechentaler Windgaellen
    2026-08-29   19.06 km  ZS-                    Ortler via neue Olaf Reinstadler-Route
    2026-09-02   24.17 km  T4 - Alpinwandern      Ronengrat & Klettergarten Gummen

### Was funktioniert

- Download von Hikr Seiten mit realistischen Browser Headern und brotli
- Extraktion der Metadaten aus der Tabelle mit der Klasse fiche_rando:
  Titel, Region, Datum, drei Schwierigkeitsskalen, Aufstieg, Abstieg,
  Zeitbedarf, GPX Link
- Normalisiertes Tourdatum, aus "12 Juli 2026" wird 2026-07-12
- GPX Download nach data/gpx, benannt nach Datum und Tourtitel, zum Beispiel
  2026-08-29-ortler-via-neue-olaf-reinstadler-route.gpx
- Distanzberechnung aus der GPX Datei mit gpxpy
- Ein Fehlschlag beendet den Lauf nicht, Ergebnisse und Fehler werden
  getrennt gesammelt
- Ablage aller Metadaten in einer lokalen SQLite Datei, Schluessel ist die
  Quelle URL, ein zweiter Lauf aktualisiert statt zu verdoppeln
- Filter ueber Region, Sportart, Schwierigkeit, Aufstieg und Gehzeit,
  beliebig kombinierbar
- 62 Tests, alle ohne Netzwerkzugriff und ohne Spuren auf der Platte

### Grundarchitektur

Drei Schichten, die sich gegenseitig nichts ueber ihre Interna verraten.

    crawler/downloader.py   holt Bytes aus dem Netz, kennt kein HTML
    parsers/hikr_parser.py  kennt Hikr, liefert ein Metadaten Dictionary
    parsers/gpx_parser.py   kennt GPX, liefert Distanz und Punktzahl
    storage/tour_store.py   kennt SQL, sonst weiss niemand davon
    main.py                 verbindet die vier, kennt die Reihenfolge

Der Ablauf je Tour:

    URL -> HTML nach data/html -> Metadaten Dictionary
                                       |
                                  GPX Link
                                       |
                            GPX Datei nach data/gpx -> Distanz
                                       |
                            vollstaendige Metadaten

Zwei Entscheidungen, die den Aufbau tragen:

- Der Downloader parst nichts. Er bekommt Titel und Datum uebergeben und
  weiss nicht, woher sie stammen. Deshalb kann spaeter ein Gipfelbuch
  Parser denselben Downloader benutzen.
- Formatwissen liegt beim jeweiligen Parser. Der HikrParser kennt deutsche
  Monatsnamen, der GpxParser kennt Tracks und Routen. Kommen weitere
  Sprachen dazu, waechst nur der HikrParser.

## Die Tourdatenbank

Alle Metadaten liegen in `data/tours.sqlite3`, einer einzelnen Datei ohne
Server. Die Datei ist per gitignore ausgeschlossen und bleibt lokal.

Gefiltert wird ueber `find_tours`. Jeder nicht gesetzte Filter bedeutet
keine Einschraenkung:

    from storage import TourStore

    with TourStore() as store:
        touren = store.find_tours(
            region="Graubuenden",
            sport="Wandern",
            min_elevation_gain=800,
            max_elevation_gain=1500,
            max_duration_minutes=360,
        )

Drei Eigenheiten, die man kennen sollte:

- Die Region ist in Land, Hauptregion und Gebiet zerlegt. Ein Filter prueft
  alle Stufen, "Schweiz" und "Oberengadin" funktionieren also beide, ohne
  dass man weiss, auf welcher Stufe der Begriff liegt.
- Umlaute sind egal. "Graubuenden" und "Graubuenden" finden dasselbe, weil
  Suchbegriff und Spaltenwert vorher normalisiert werden.
- Mehrtaegige Touren haben keine Gehzeit in Minuten, sondern eine Anzahl
  Tage. Ein Filter auf die Gehzeit laesst sie deshalb heraus, eine
  Sechstagestour ist keine Tour unter fuenf Stunden.

## Roadmap

### Als naechstes
- Kommandozeilen Interface fuer die Datenbankabfrage, damit die Filter
  ohne Python Zeile erreichbar sind
- Extraktion des Beschreibungstexts

### Spaeter
- Mehrsprachigkeit im Parser (de, fr, it, en)
- Extraktion des Beschreibungstexts
- Schluesselwort Extraktion aus Tourbeschreibungen
- Automatische Tag Vergabe (z.B. bruechig, lohnenswert, ausgesetzt,
  familientauglich)
- Filterung nach Tags zusaetzlich zu den strukturierten Metadaten
- Zweiter Parser fuer weitere Websites wie Gipfelbuch

## Setup

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    python main.py

Tests:

    pytest

## Verzeichnisse

- crawler   Download von Webseiten und Dateien
- parsers   Extraktion aus Webseiten und aus GPX Dateien
- data      Lokale Ablage von HTML, GPX und Exports, nicht im Repo
- tests     Testcode
- main.py   Orchestrierung ueber die Liste TOUR_URLS
