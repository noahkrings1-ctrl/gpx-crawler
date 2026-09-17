# GPX Crawler Projekt

## Ziel
Python Crawler, der Tourenberichte auf Hikr.org analysiert
und GPX Dateien samt Metadaten extrahiert. Spaeter erweiterbar um weitere Websites wie Gipfelbuch.
Aufbau einer Hochtouren Metadaten Datenbank, mit der gezielt Regionen gefiltert und gesucht werden können.

## Aktueller Stand (September 2026)

Die Kette steht: Discovery oder feste Liste -> Tourseite -> Metadaten -> GPX
-> Distanz -> SQLite -> Suche mit query.py. Den aktuellen Datenbestand zeigt
die Datenbank selbst. Zahlen stehen hier bewusst nicht, sie wuerden nach
jedem Lauf veralten.

### Discovery
- crawler/discovery.py, Klasse HikrDiscovery mit DiscoveryError. find_urls
  und discover blaettern durch die Liste region{ID}/{code}/ mit ?skip=10er
  Schritten und liefern Tour URLs
- Kategoriecodes: tour alle, ped Wandern, alp Hochtouren, esc Klettern, ski
  Skitouren, raq Schneeschuhe, via Klettersteig, eis Eisklettern
- Region als ID oder als Name aus REGION_IDS, abgelesen an echten Regionsseiten
  (Schweiz 2, Uri 146, Graubuenden 4, die uebrigen Kantone, Frankreich 14,
  Italien 16, Oesterreich 33, Deutschland 69)
- Die Listen sind nach Tourdatum absteigend sortiert, jeder Eintrag zeigt sein
  Datum als "19 Mär 26". Ein Datumsbereich wird daraus gelesen, ein Eintrag
  vor dem Beginn beendet die Suche
- Die naechste Seite ist der Blaetterlink mit skip + 10, gefunden ueber die
  Zahl, nicht ueber die Beschriftung. Gefolgt wird nur Links derselben Region
  und Kategorie
- Strukturwaechter: Blaetterblock ohne Eintraege oder nicht absteigende Daten
  bei Datumsfilter ergeben einen DiscoveryError
- --schwierigkeit und --tourtyp filtern schon auf der Listenseite. Jeder
  Eintrag traegt seine Noten als Paare aus Skala und Kurzform, etwa
  (hochtouren, WS). Nicht passende Touren werden nie angefragt. Jeder Filter
  ist eine eigene Suche: Suchstand und offene URLs laufen unter search_key,
  etwa ped:t4,t5,t6 oder alp:ws,zs|ski-hochtour. Der Datumsbereich endet
  trotzdem am ersten zu alten Eintrag, egal welche Bewertung er traegt
- main.py fuehrt den Lauf: zuerst offene URLs frueherer Laeufe, fuer den Rest
  Discovery ab gespeichertem Stand minus eine Seite. Vollstaendige Bereiche
  werden nur oben nach neuen Berichten abgesucht (stop_at_known_page)
- Erster echter Lauf im September 2026 fuer Uri Skitouren: mit --nur-urls
  2 Anfragen, danach 5 Touren mit 11 Anfragen in 22 Sekunden. Keine Sperre,
  Seitenstruktur und Tourdaten passten zum Parser

### Crawler
- Downloader mit Browser Headern und brotli Support. Drossel, robots.txt und
  Wiederholungen sind optionale Parameter, echte Laeufe bekommen alle drei
  ueber build_polite_downloader
- Fehlerklassen: DownloadError dauerhaft, TransientDownloadError voruebergehend,
  CrawlBlockedError beendet den ganzen Lauf
- download_gpx legt GPX Dateien nach data/gpx ab, benannt nach Datum und
  Titel, z.B. 2026-07-12-sunnig-wichel-via-nordgrat.gpx. Liegt die Datei schon
  vor, gibt es keine Anfrage
- Ist nur die GPX Datei dauerhaft unbrauchbar (kein GPX, HTTP 404, nicht
  lesbar), wird die Tour trotzdem gespeichert, ohne gpx_path und Distanz.
  Voruebergehende GPX Fehler lassen die Tour offen, sie wird erneut versucht
- HTML und GPX werden atomar geschrieben, ueber eine .part Datei
- main.py hat zwei Modi: ohne Optionen die feste Liste TOUR_URLS, mit
  --discover die Suche nach Kriterien. Vorhandenes HTML wird wiederverwendet

### Parser
- HikrParser liest die Tabelle fiche_rando ueber LABEL_MAP, nur deutsche Labels
- Rohfelder bleiben erhalten, daneben stehen normalisierte Felder: date_iso,
  elevation_gain_m, elevation_loss_m, time_required_min, duration_days
- Der Zeitbedarf hat zwei Formate. 5:00 wird zu 300 Minuten, 6 Tage landet in
  duration_days. Eine Umrechnung in Minuten waere irrefuehrend
- Die Region ist zerlegt in region_country, region_main und region_area, dazu
  region_leaf. region_main ist in der Schweiz der Kanton, in Oesterreich eine
  Gebirgsgruppe, daher der neutrale Name
- Vier Skalen: Wandern, Hochtouren, Klettern, Ski. Die Ski Skala heisst auf
  Listen und Tourseiten "Ski Schwierigkeit", bestaetigt beim ersten echten
  Lauf. LABEL_MAP versteht zusaetzlich "Skitouren Schwierigkeit" als Rueckfall
- sport: Skitour vor Hochtour vor Wandern vor Klettern. Eine UIAA Note neben
  einer T Note ist nur eine Kletterstelle
- main_text kommt nur aus div#main_text, nicht aus der ganzen Seite
- parsers/grades.py haelt die Regeln fuer Stufen und Tourtypen. Discovery und
  Ablage nutzen dieselben Funktionen. Stufen werden exakt verglichen: ZS
  trifft ZS-, ZS und ZS+, S nicht WS, II nicht III. Was keine Stufe ist,
  wird abgelehnt
- Tourtypen fuer Touren mit Hochtourennote: ski-hochtour (mit Skinote),
  alpinwandern-hochtour (mit T4 bis T6, ohne Skinote), hochtour (weder noch)
- GpxParser berechnet die Distanz horizontal in Kilometern mit gpxpy. Routen
  ohne Track werden mitgezaehlt, ohne verwertbare Punkte gibt es None statt 0.0

### Ablage
- TourStore in storage/tour_store.py, Datei data/tours.sqlite3
- Tabelle tours mit 27 Spalten, neu sind difficulty_ski und main_text.
  Schluessel ist source_url, upsert statt Duplikat, created_at bleibt erhalten
- Tabelle discovered_urls: jede bekannte URL einmal, Status neu, gespeichert
  oder fehlgeschlagen, dazu Region, Kategorie und Tourdatum aus der Liste
- Tabelle discovery_progress: resume_skip und completed je Region, Kategorie
  und Zeitraum. completed bleibt gesetzt, wenn es einmal gesetzt war
- find_tours filtert nach region, sport, difficulty, tour_type,
  min_elevation_gain, max_elevation_gain, max_duration_minutes, date_from,
  date_to und text, dazu order_by, descending und limit. Fehlender Filter
  heisst kein Filter
- region und text vergleichen als Teiltext nach normalise (klein geschrieben,
  Umlaute ausgeschrieben), damit "Österreich" und "Oesterreich" dasselbe
  finden. text sucht in main_text und title
- difficulty vergleicht die Stufe exakt ueber die SQL Funktion grade_match,
  tour_type filtert ueber die SQL Funktion tour_type. Beide kommen aus
  parsers/grades.py
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
- --von und --bis nehmen Jahr oder Datum, ein Jahr steht fuer das ganze Jahr
- --text sucht im Berichtstext und im Titel
- --tourtyp waehlt ski-hochtour, alpinwandern-hochtour oder hochtour

### Tests
- Alle Tests laufen ohne Netz und ohne Spuren auf der Platte
- tests/conftest.py hat drei Helfer: Waechter fuer data/tours.sqlite3,
  Netzwaechter, der jede echte Socket Verbindung sperrt, und fake_clock, eine
  Uhr, die nur beim Schlafen vorrueckt. Pausen werden damit ohne Warten geprueft
- tests/fixtures/hikr enthaelt Nachbauten von Listenseiten und robots.txt mit
  erfundenen Titeln, Daten und Nummern. Keine echten Hikr Seiten ins Repo
- Schreibende Tests nutzen tmp_path, reine Abfragetests ":memory:"
- pyproject.toml konfiguriert pytest mit pythonpath und testpaths

## Konventionen zu Rate Limits und Fairness
- Jede Anfrage an Hikr laeuft ueber build_polite_downloader. HikrDiscovery
  verweigert einen Downloader ohne limiter
- Mindestpause 2 Sekunden zwischen zwei Anfragen (MIN_DELAY_SECONDS). Der
  RateLimiter laesst keinen kleineren Wert zu. www.hikr.org und f.hikr.org
  teilen sich eine Drossel. Keine parallelen Anfragen
- robots.txt wird vor jeder Anfrage geprueft, einmal je Host und Lauf geladen,
  erst wenn wirklich eine Anfrage ansteht. 5xx, Netzfehler, 401 und 403 auf
  robots.txt heissen: nicht crawlen
- Wiederholungen nur bei Netzfehlern und 502, 503, 504, hoechstens zwei, nach
  15 und 60 Sekunden. 429 mit Retry-After bis 300 Sekunden wird einmal
  abgewartet. 403, 429 sonst und Cloudflare Pruefungen beenden den Lauf
- Drei Fehlschlaege in Folge beenden den Lauf
- Discovery nur mit --discover, nie beim Start. Standard 20, hoechstens 100
  neue URLs und hoechstens 20 Listenseiten je Aufruf
- Keine URL wird zweimal gecrawlt. Gespeicherte und dauerhaft fehlgeschlagene
  URLs werden ohne Anfrage uebersprungen, eine Option dagegen gibt es nicht
- Nie nutzen, weil robots.txt es sperrt: Nutzerlisten wie /user/*/ski/, den
  Monatsfilter date_year_month, map.php, print_rando.php. Die Tour Sitemap
  hat der Betreiber auskommentiert, sie ist kein Discovery Weg
- Keine Cloudflare Pruefung umgehen. Die Browser Kennung bleibt nach
  Entscheidung vom September 2026 bestehen, weitere Tarnung gibt es nicht
- Hikr Texte gehen an kein KI Modell. robots.txt setzt ai-train=no und sperrt
  KI Crawler, das Urheberrecht an Texten und Bildern liegt bei den Autoren
- Waehrend der Entwicklung fragt Claude Hikr nicht selbst an. Neue Tests
  laufen gegen Nachbauten in tests/fixtures

## Bekannte Grenzen
- Die Schwierigkeit ist kein Bereichsfilter, bis WS geht noch nicht
- Nur deutschsprachige Hikr Seiten, die Spalte language wird nicht befuellt
- Die Mountainbike Skala wird verworfen
- Keine Schemamigration. CREATE TABLE IF NOT EXISTS ergaenzt keine Spalten in
  einer bestehenden Datei, neue Spalten brauchen eine neue Datenbankdatei
- Geloeschte oder nachtraeglich mit altem Datum eingetragene Berichte kann die
  Discovery in einem durchsuchten Bereich uebersehen
- Die Fixtures sind Nachbauten. Eine geaenderte Hikr Seite faellt erst im
  echten Lauf auf, dort meldet sie der Strukturwaechter

## Architektur
- crawler/politeness.py     RateLimiter, RobotsPolicy, RetryPolicy und Grenzwerte
- crawler/downloader.py     Klasse Downloader mit DownloadError,
                            TransientDownloadError, CrawlBlockedError
- crawler/discovery.py      Klasse HikrDiscovery mit DiscoveryError
- parsers/hikr_parser.py    Klasse HikrParser mit LABEL_MAP
- parsers/gpx_parser.py     Klasse GpxParser mit GpxParseError
- parsers/grades.py         Stufen und Tourtypen fuer Discovery und Ablage
- storage/tour_store.py     Klasse TourStore mit TourStoreError, einziges SQL
- data/html                 Lokale HTML Ablage, per gitignore ausgeschlossen
- data/gpx                  Lokale GPX Ablage, per gitignore ausgeschlossen
- data/tours.sqlite3        Tourdatenbank, per gitignore ausgeschlossen
- tests                     pytest Tests, conftest.py mit Waechtern
- tests/fixtures/hikr       Nachbauten von Hikr Listenseiten und robots.txt
- main.py                   Crawl Lauf ueber TOUR_URLS oder die Discovery
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
- Keine Zahlen zum Datenbestand und keine Testanzahl in README und CLAUDE.md.
  Sie veralten nach jedem Lauf. Den Bestand zeigt query.py, die Testanzahl
  zeigt pytest

## Danach geplant
- Tags per Wortliste auf main_text, in einer verknuepften Tabelle
- Filterung nach Tags in find_tours und query.py
- Mehrsprachigkeit im Parser (de, fr, it, en)
- Spaeter Bereichsfilter fuer die Schwierigkeit, z.B. bis WS
- Spaeter Volltextsuche mit FTS5, das eingebaute SQLite bringt es mit
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
- Tags entstehen ausschliesslich ueber lokale Wortlisten pro Kategorie
- Kein NLP Dienst und kein LLM auf Hikr Texten. robots.txt setzt ai-train=no
  und sperrt KI Crawler, die Texte gehoeren ihren Autoren
- Gespeichert werden die abgeleiteten Tags je Tour in einer verknuepften
  Tabelle

### Filterung
- Kombinierbare Filter, z.B. "Skitour im Wallis, Schwierigkeit bis WS,
  Aufstieg unter 1500 m, mit Tag lohnenswert und ohne Tag ueberlaufen"
- Ausgabe als sortierte Liste im Terminal, spaeter evtl. als kleine Web UI
