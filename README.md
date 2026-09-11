# GPX Webcrawler

Ein Python Crawler, der Tourenberichte auf Hikr.org liest, die GPX Dateien
herunterlaedt und alle Metadaten in einer lokalen, durchsuchbaren
Tourdatenbank ablegt.

## Stand September 2026

Die ganze Kette steht und laeuft gegen die echte Website:

    Hikr URL -> Metadaten -> GPX Datei -> Distanz -> SQLite -> Suche mit query.py

Die Ablage enthaelt zwoelf echte Touren, 11 Wanderungen und 1 Hochtour aus
der Schweiz (6), Oesterreich (3), Italien (2) und Liechtenstein (1). 8 davon
haben eine GPX Datei. Letzter Lauf: 12 gelesen, 0 Fehlschlaege.

### Was funktioniert

Crawler

- Download von Hikr Seiten mit realistischen Browser Headern und brotli
- GPX Download nach data/gpx, benannt nach Datum und Titel, zum Beispiel
  2026-08-29-ortler-via-neue-olaf-reinstadler-route.gpx
- Ein Fehlschlag beendet den Lauf nicht. Bereits geladenes HTML wird
  wiederverwendet, zwischen zwei Aufrufen liegt eine Pause

Parser

- Metadaten aus der Tabelle fiche_rando: Titel, Region, Datum, drei
  Schwierigkeitsskalen, Aufstieg, Abstieg, Zeitbedarf, GPX Link
- Zahlen statt Text: Aufstieg und Abstieg in Metern, Gehzeit in Minuten,
  mehrtaegige Touren als Anzahl Tage, Datum als 2026-07-12
- Region zerlegt in Land, Hauptregion und Gebiet
- Sportart abgeleitet aus der Schwierigkeitsskala
- Distanz aus der GPX Datei mit gpxpy

Ablage und Suche

- SQLite Datei data/tours.sqlite3. Schluessel ist die Quelle URL, ein
  zweiter Lauf aktualisiert statt zu verdoppeln
- Filter nach Region, Sportart, einer oder mehreren Schwierigkeiten,
  Aufstieg von bis und maximaler Gehzeit, beliebig kombinierbar
- Suchinterface query.py mit Tabellenausgabe

Tests

- 96 Tests, alle ohne Netzwerkzugriff und ohne Spuren auf der Platte

### Grundarchitektur

Jeder Baustein kennt nur sein eigenes Fachgebiet:

    crawler/downloader.py   holt Bytes aus dem Netz, kennt kein HTML
    parsers/hikr_parser.py  kennt Hikr, liefert ein Metadaten Dictionary
    parsers/gpx_parser.py   kennt GPX, liefert Distanz und Punktzahl
    storage/tour_store.py   kennt SQL, sonst weiss niemand davon
    main.py                 fuehrt die Kette fuer die Liste TOUR_URLS aus
    query.py                uebersetzt Kommandozeilenargumente in eine Suche

Der Ablauf je Tour in main.py:

    URL -> HTML nach data/html -> HikrParser -> Metadaten Dictionary
                                                       |
                                                   GPX Link
                                                       |
                                  GPX Datei nach data/gpx -> GpxParser -> Distanz
                                                       |
                                  TourStore.upsert_tour -> data/tours.sqlite3

Drei Entscheidungen, die den Aufbau tragen:

- Der Downloader parst nichts. Er bekommt Titel und Datum uebergeben und
  weiss nicht, woher sie stammen. Deshalb kann spaeter ein Gipfelbuch
  Parser denselben Downloader benutzen.
- Formatwissen liegt beim jeweiligen Parser. Der HikrParser kennt deutsche
  Monatsnamen, der GpxParser kennt Tracks und Routen. Kommen weitere
  Sprachen dazu, waechst nur der HikrParser.
- Das gesamte SQL steht in storage/tour_store.py. Kein sqlite3.Error
  verlaesst die Ablage, alles wird zu TourStoreError. Ein Wechsel auf
  SQLAlchemy betraefe nur dieses eine Modul.

## Die Tourdatenbank

Alle Metadaten liegen in `data/tours.sqlite3`, einer einzelnen Datei ohne
Server. Die Datei ist per gitignore ausgeschlossen und bleibt lokal.

### Suchen auf der Kommandozeile

`query.py` ist das Suchinterface. Jeder nicht gesetzte Filter bedeutet keine
Einschraenkung, ohne Angabe kommt die ganze Ablage:

    python query.py --region Schweiz --sportart Wandern
    python query.py --max-aufstieg 1500 --max-dauer 5:30
    python query.py --schwierigkeit T4 --min-aufstieg 800
    python query.py --sportart Wandern --schwierigkeit T4 T5
    python query.py --sortierung distance_km --absteigend --limit 5

Die Ausgabe ist eine Tabelle mit Datum, Sportart, Region, Schwierigkeit,
Aufstieg, Dauer, Distanz und Titel:

    Datum       Sportart  Region       Schwierigkeit       Aufstieg  Dauer  Distanz    Titel
    2026-08-01  Wandern   Tessin       T3 - anspruchsv...  650 m     5:00   16.83 km   Passo Bornengo
    2026-08-12  Wandern   Uri          T5 - anspruchsv...  1270 m    5:30   13.08 km   Laeged und Schaechentaler
    2026-09-02  Wandern   Nidwalden    T4 - Alpinwandern   1380 m    4:00   24.17 km   Ronengrat & Klettergarten

    3 Touren gefunden.

`--max-dauer` versteht beide Schreibweisen, `5:30` und `330`.

`--schwierigkeit` nimmt einen oder mehrere Werte. `--schwierigkeit T4 T5` und
`--schwierigkeit T4 --schwierigkeit T5` sind gleichwertig. Mehrere Werte gelten
untereinander als oder, mit den uebrigen Filtern bleibt es bei und.

Alle Optionen zeigt `python query.py --help`.

### Aus Python heraus

    from storage import TourStore

    with TourStore() as store:
        touren = store.find_tours(
            region="Schweiz",
            sport="Wandern",
            difficulty=["T4", "T5"],
            min_elevation_gain=800,
            max_elevation_gain=1500,
            max_duration_minutes=360,
        )

Mit den aktuellen Daten liefert das zwei Touren: Laeged und Schaechentaler
Windgaellen (T5, Uri) und Ronengrat (T4, Nidwalden).

### Worauf man beim Filtern achten sollte

- Die Region ist in Land, Hauptregion und Gebiet zerlegt. Ein Filter prueft
  alle Stufen, "Schweiz" und "Oberengadin" funktionieren also beide, ohne
  dass man weiss, auf welcher Stufe der Begriff liegt.
- Umlaute sind egal. "Graubünden" und "Graubuenden" finden dasselbe, weil
  Suchbegriff und Spaltenwert vorher normalisiert werden.
- Mehrtaegige Touren haben keine Gehzeit in Minuten, sondern eine Anzahl
  Tage. Ein Filter auf die Gehzeit laesst sie deshalb heraus, eine
  Sechstagestour ist keine Tour unter fuenf Stunden.
- Die Schwierigkeit wird als Teiltext in allen drei Skalen verglichen. T3
  trifft auch T3+ und ZS auch ZS-, II aber auch III. Einzelne Buchstaben wie
  S oder L treffen fast jede Tour.

## Bekannte Grenzen

- Die Schwierigkeit laesst sich nicht als Bereich filtern, "bis WS" geht noch
  nicht.
- Der Parser kennt nur deutschsprachige Hikr Seiten. Die Spalte language
  existiert, wird aber nicht befuellt.
- Es gibt keine Schemamigration. Neue Spalten brauchen eine neue
  Datenbankdatei, beim Neuaufbau wird das HTML wiederverwendet, die GPX
  Dateien werden neu geladen.
- Die zu crawlenden Touren stehen als feste Liste TOUR_URLS in main.py.

## Roadmap

### Als naechstes

- Extraktion des Beschreibungstexts
- Mehrsprachigkeit im Parser (de, fr, it, en)

### Spaeter

- Bereichsfilter fuer die Schwierigkeit, zum Beispiel bis WS
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
    python query.py --help

Tests:

    pytest

## Verzeichnisse

- crawler   Download von Webseiten und Dateien
- parsers   Extraktion aus Webseiten und aus GPX Dateien
- storage   Ablage der Metadaten in SQLite
- data      Lokale Ablage von HTML, GPX und der Datenbank, nicht im Repo
- tests     Testcode
- main.py   Crawl Lauf ueber die Liste TOUR_URLS
- query.py  Suche in der Ablage mit Tabellenausgabe
