# GPX Webcrawler

Ein Python Crawler, der Tourenberichte auf Hikr.org findet und liest, die GPX
Dateien herunterlaedt und alle Metadaten in einer lokalen, durchsuchbaren
Tourdatenbank ablegt.

## Stand September 2026

Die ganze Kette steht:

    Discovery oder feste Liste -> Tourseite -> Metadaten -> GPX -> Distanz -> SQLite -> query.py

Neu ist die Discovery. Statt einer festen URL Liste lassen sich Kriterien
angeben, etwa Skitouren in Uri zwischen 2020 und 2026, und der Crawler sucht
die passenden Berichte selbst. Gecrawlt wird dabei gedrosselt, nach den Regeln
der robots.txt und ohne eine URL je zweimal anzufragen.

Wie viele Touren die Ablage gerade enthaelt, zeigt `python query.py`, die
Anzahl steht am Ende der Tabelle.

### Was funktioniert

Discovery

- Suche ueber die Listen je Region und Kategorie, zum Beispiel alle Skitouren
  in Uri
- Datumsbereich von bis, gelesen aus den normalen Listen
- Weitermachen ueber mehrere Laeufe, jeder Lauf bringt neue Touren
- Keine URL wird zweimal gecrawlt, auch nicht ueber beide Modi hinweg

Crawler

- Mindestens 2 Sekunden Pause zwischen zwei Anfragen an Hikr
- robots.txt wird vor jeder Anfrage geprueft
- Wiederholungen nur bei Netz und Serverfehlern, Abbruch bei 403, 429 und
  Cloudflare Pruefungen
- GPX Download nach data/gpx, benannt nach Datum und Titel, vorhandene Dateien
  werden nicht erneut geladen
- Ist nur die GPX Datei kaputt, wird die Tour trotzdem gespeichert, ohne GPX
  und Distanz

Parser

- Metadaten aus der Tabelle fiche_rando: Titel, Region, Datum, vier
  Schwierigkeitsskalen inklusive Ski, Aufstieg, Abstieg, Zeitbedarf, GPX Link
- Berichtstext fuer die Stichwortsuche
- Zahlen statt Text: Aufstieg und Abstieg in Metern, Gehzeit in Minuten,
  mehrtaegige Touren als Anzahl Tage, Datum als 2026-07-12
- Region zerlegt in Land, Hauptregion und Gebiet
- Sportart abgeleitet aus der Schwierigkeitsskala
- Distanz aus der GPX Datei mit gpxpy

Ablage und Suche

- SQLite Datei data/tours.sqlite3 mit Touren, bekannten URLs und Suchstand
- Filter nach Region, Sportart, Schwierigkeit, Aufstieg, Gehzeit,
  Datumsbereich und Stichwort, beliebig kombinierbar
- Suchinterface query.py mit Tabellenausgabe

Tests

- Alle Tests laufen ohne Netzwerkzugriff und ohne Spuren auf der Platte

### Grundarchitektur

Jeder Baustein kennt nur sein eigenes Fachgebiet:

    crawler/politeness.py   Pausen, robots.txt und Wiederholungen fuer jede Anfrage
    crawler/downloader.py   holt Bytes aus dem Netz, kennt kein HTML
    crawler/discovery.py    findet Tour URLs in den Hikr Listen
    parsers/hikr_parser.py  kennt Hikr Tourseiten, liefert ein Metadaten Dictionary
    parsers/gpx_parser.py   kennt GPX, liefert Distanz und Punktzahl
    storage/tour_store.py   kennt SQL, sonst weiss niemand davon
    main.py                 fuehrt die Kette aus, mit fester Liste oder Discovery
    query.py                uebersetzt Kommandozeilenargumente in eine Suche

Der Ablauf eines Laufs:

    python main.py --discover ...              python main.py
              |                                      |
    Liste je Region und Kategorie               TOUR_URLS
    durchblaettern, Suchstand merken                 |
              |                                      |
              +---------------- URLs ----------------+
                                 |
                  schon gespeichert oder dauerhaft
                  fehlgeschlagen? ueberspringen
                                 |
         Tourseite -> HikrParser -> GPX -> GpxParser -> TourStore

Vier Entscheidungen, die den Aufbau tragen:

- Der Downloader parst nichts. Er bekommt Titel und Datum uebergeben und
  weiss nicht, woher sie stammen. Deshalb kann spaeter ein Gipfelbuch Parser
  denselben Downloader benutzen.
- Formatwissen liegt beim jeweiligen Parser. Der HikrParser kennt deutsche
  Monatsnamen, der GpxParser kennt Tracks und Routen, die Discovery kennt die
  Listenseiten. Kommen weitere Sprachen dazu, waechst nur der jeweilige Parser.
- Das gesamte SQL steht in storage/tour_store.py. Kein sqlite3.Error verlaesst
  die Ablage, alles wird zu TourStoreError. Ein Wechsel auf SQLAlchemy
  betraefe nur dieses eine Modul.
- Jede Anfrage folgt denselben Hoeflichkeitsregeln. Discovery, Tourseiten und
  GPX Dateien laufen ueber denselben gedrosselten Downloader, und die
  Discovery verweigert den Dienst ohne Drossel.

## Discovery

    python main.py --discover --region 146 --kategorie skitouren --max 20
    python main.py --discover --region Uri --kategorie skitouren --von 2020 --bis 2026 --max 90
    python main.py --discover --region 146 --kategorie ski --nur-urls
    python main.py --discover --region 146 --kategorie wandern --von 2026 --bis 2026 --schwierigkeit T4 T5 T6

Ohne `--discover` arbeitet `main.py` ausschliesslich die feste Liste
TOUR_URLS ab. Die Discovery startet nie von selbst.

| Option | Bedeutung |
|---|---|
| `--region` | ID aus der URL der Regionsseite, etwa 146 aus region146.html fuer Uri, oder ein hinterlegter Name wie Uri, Graubünden, Schweiz |
| `--kategorie` | alle, wandern, hochtouren, klettern, skitouren, schneeschuhe, klettersteig, eisklettern, oder der Hikr Code wie ski |
| `--von`, `--bis` | Tourdatum als Jahr oder Datum, beide Grenzen eingeschlossen |
| `--schwierigkeit` | nur Eintraege mit dieser Bewertung, z.B. T4 T5 T6 fuer Alpinwanderungen. Mehrere Werte gelten als oder, verglichen wird als Teiltext |
| `--max` | neue Touren je Lauf, Standard 20, hoechstens 100 |
| `--nur-urls` | gefundene URLs nur anzeigen und vormerken, keine Tour laden |

So arbeitet sie:

- Hikr zeigt je Region und Kategorie eine Liste mit zehn Berichten je Seite,
  nach Tourdatum absteigend sortiert. Die Discovery blaettert darin, hoechstens
  20 Seiten je Lauf.
- Ein Datumsbereich wird aus den Eintraegen dieser Liste gelesen. Hikrs
  eigener Monatsfilter ist per robots.txt gesperrt und wird nicht benutzt.
  Sobald ein Eintrag vor dem Beginn des Bereichs auftaucht, ist er durchsucht.
- Jeder Lauf merkt sich, bis wohin er gekommen ist. Der naechste setzt dort an,
  eine Seite frueher als Ueberlappung. Ist ein Bereich vollstaendig, sieht ein
  weiterer Lauf nur oben nach neuen Berichten.
- Gefundene URLs landen sofort mit Status neu in der Datenbank. Mit
  `--nur-urls` bleiben sie dort, der naechste Lauf laedt sie zuerst.
- Ein Filter auf die Schwierigkeit wird schon auf der Listenseite geprueft,
  sie zeigt jede Bewertung in Kurzform, etwa T4-. Nicht passende Touren
  werden nie angefragt. Der Filter ist eine eigene Suche mit eigenem Stand.

Doppeltes Crawlen ist ausgeschlossen:

- Jede URL steht hoechstens einmal in der Tabelle discovered_urls, ein
  Duplikat laesst die Datenbank nicht zu.
- Bekannte URLs liefert die Discovery nicht zurueck.
- Gespeicherte und dauerhaft fehlgeschlagene URLs ueberspringt ein Lauf ohne
  jede Anfrage, in beiden Modi.
- Eine Option zum erneuten Laden gibt es nicht.
- Voruebergehende Fehler wie ein Netzausfall zaehlen nicht als gecrawlt, die
  URL bleibt offen und kommt im naechsten Lauf wieder dran.

## Fairness und Rate Limits

| Regel | Wert |
|---|---|
| Pause zwischen zwei Anfragen | mindestens 2 Sekunden, nicht unterschreitbar |
| Geltungsbereich | eine gemeinsame Drossel fuer www.hikr.org und f.hikr.org |
| Parallele Anfragen | keine |
| robots.txt | vor jeder Anfrage geprueft, einmal je Lauf geladen, erst bei Bedarf |
| robots.txt nicht erreichbar oder gesperrt | kein Crawlen |
| Netzfehler, 502, 503, 504 | hoechstens 2 Wiederholungen, nach 15 und 60 Sekunden |
| 429 mit Retry-After bis 5 Minuten | einmal abwarten |
| 429 sonst, 403, Cloudflare Pruefung | ganzer Lauf endet sofort |
| 3 Fehlschlaege in Folge | ganzer Lauf endet |
| Treffer je Discovery Lauf | Standard 20, hoechstens 100 |

Aus der robots.txt von Hikr, Stand September 2026:

- Erlaubt und genutzt: Regions und Kategorielisten mit skip, Tourseiten,
  GPX Dateien.
- Gesperrt und nicht genutzt: Listen einzelner Nutzer wie /user/.../ski/, der
  Monatsfilter date_year_month, map.php, print_rando.php.
- Content-Signal: search=yes, ai-train=no, use=reference. KI Crawler sind
  vollstaendig gesperrt.

Daraus folgt fuer das Projekt:

- Tags entstehen nur ueber lokale Wortlisten. Hikr Texte gehen an kein KI
  Modell.
- Texte, Fotos und GPX Dateien bleiben lokal. Das Urheberrecht liegt bei den
  Autoren, das Repository enthaelt keine Hikr Inhalte. Die Test Fixtures sind
  Nachbauten mit erfundenen Titeln.

## Die Tourdatenbank

Alle Daten liegen in `data/tours.sqlite3`, einer einzelnen Datei ohne Server.
Die Datei ist per gitignore ausgeschlossen und bleibt lokal.

    tours               eine Zeile je gespeicherter Tour
    discovered_urls     jede bekannte URL mit Status neu, gespeichert oder fehlgeschlagen
    discovery_progress  Suchstand je Region, Kategorie und Zeitraum

### Suchen auf der Kommandozeile

`query.py` ist das Suchinterface. Jeder nicht gesetzte Filter bedeutet keine
Einschraenkung, ohne Angabe kommt die ganze Ablage:

    python query.py --region Schweiz --sportart Wandern
    python query.py --max-aufstieg 1500 --max-dauer 5:30
    python query.py --sportart Wandern --schwierigkeit T4 T5
    python query.py --sportart Skitour --von 2020 --bis 2025
    python query.py --text biwak
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

`--von` und `--bis` nehmen ein Jahr oder ein Datum. Ein Jahr steht fuer das
ganze Jahr.

`--text` sucht im Berichtstext und im Titel.

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

### Worauf man beim Filtern achten sollte

- Die Region ist in Land, Hauptregion und Gebiet zerlegt. Ein Filter prueft
  alle Stufen, "Schweiz" und "Oberengadin" funktionieren also beide, ohne
  dass man weiss, auf welcher Stufe der Begriff liegt.
- Umlaute sind egal. "Graubünden" und "Graubuenden" finden dasselbe, weil
  Suchbegriff und Spaltenwert vorher normalisiert werden.
- Mehrtaegige Touren haben keine Gehzeit in Minuten, sondern eine Anzahl
  Tage. Ein Filter auf die Gehzeit laesst sie deshalb heraus, eine
  Sechstagestour ist keine Tour unter fuenf Stunden.
- Die Schwierigkeit wird als Teiltext in allen Skalen verglichen. T3 trifft
  auch T3+ und ZS auch ZS-, II aber auch III. Einzelne Buchstaben wie S oder
  L treffen fast jede Tour.
- Ein Datumsfilter laesst Touren ohne Datum heraus.
- Die Stichwortsuche findet nur, was schon heruntergeladen ist.

## Bekannte Grenzen

- Die Schwierigkeit laesst sich nicht als Bereich filtern, "bis WS" geht noch
  nicht.
- Der Parser kennt nur deutschsprachige Hikr Seiten. Die Spalte language
  existiert, wird aber nicht befuellt.
- Die Mountainbike Skala wird verworfen.
- Es gibt keine Schemamigration. Neue Spalten brauchen eine neue
  Datenbankdatei. Der Neuaufbau kommt ohne Netz aus, weil HTML und GPX
  Dateien lokal liegen.
- Regionsnamen kennt die Discovery nur fuer hinterlegte Regionen, alle anderen
  gehen ueber ihre ID.
- Wird ein Bericht geloescht oder nachtraeglich mit altem Datum eingetragen,
  kann die Discovery ihn in einem bereits durchsuchten Bereich uebersehen.
- Die Tests arbeiten mit Nachbauten der Listenseiten. Aendert Hikr seine Seiten,
  faellt das erst im echten Lauf auf. Ein Strukturwaechter meldet es dann,
  statt still leere Ergebnisse zu liefern.

## Roadmap

### Als naechstes

- Tags per Wortliste auf dem Berichtstext, z.B. bruechig, lohnenswert,
  ausgesetzt, familientauglich
- Filterung nach Tags zusaetzlich zu den strukturierten Metadaten
- Mehrsprachigkeit im Parser (de, fr, it, en)

### Spaeter

- Bereichsfilter fuer die Schwierigkeit, zum Beispiel bis WS
- Volltextsuche mit SQLite FTS5, sobald die Datenmenge es verlangt
- Zweiter Parser fuer weitere Websites wie Gipfelbuch

## Setup

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    python main.py
    python main.py --discover --region 146 --kategorie skitouren --nur-urls
    python query.py --help

Tests:

    pytest

## Verzeichnisse

- crawler         Download, Hoeflichkeitsregeln und Discovery
- parsers         Extraktion aus Tourseiten und aus GPX Dateien
- storage         Ablage der Metadaten in SQLite
- data            Lokale Ablage von HTML, GPX und der Datenbank, nicht im Repo
- tests           Testcode
- tests/fixtures  Nachbauten von Hikr Listenseiten fuer die Tests
- main.py         Crawl Lauf ueber die feste Liste oder die Discovery
- query.py        Suche in der Ablage mit Tabellenausgabe
