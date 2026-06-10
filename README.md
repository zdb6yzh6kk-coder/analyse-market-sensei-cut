# Analyse Market Sensei Cut

Eine Streamlit-App fuer einfache Marktdatenanalyse. Sie laeuft lokal auf dem Mac
und ist fuer einen sicheren MVP-Launch auf Streamlit Community Cloud vorbereitet.

Die App fuehrt keine Orders aus, enthaelt keine Broker-Anbindung und ist kein
Trading-System. Sie zeigt Trends, Scores, relative Staerke und CSV-Reports.

## Status

- Streamlit Dashboard
- yfinance Marktdaten mit lokalem Cache und optionalem Alpha-Vantage-Fallback
- Datenqualitaet pro Symbol: `live`, `delayed`, `cache`, `fehlerhaft`
- DuckDB Speicherung
- Plotly Charts
- Dashboard, Watchlist, Reports, Updates und Settings
- Startseite **Heute ansehen** mit Ampel, wichtigen Karten und gespeicherten Screens
- Workspace mit Schnellblick, gespeicherten Themen und Datensammlung
- Dashboard-Startansicht mit Watchlist links und Chart rechts
- Watchlist-Klick laedt den Chart direkt in der Dashboard-Arbeitsflaeche
- Vollbild-Chart mit eigenem Symbol-Schnellwechsel
- Market Summary und Watchlist Summary als kompakte Kurzfassung
- Sektorrotation mit US-Sektoren, Bau, Rohstoffen, Krypto, US-Dollar-Index und Treasury-Proxies
- Candlestick-Chart mit EMA20/50/100/200 und Volumen
- Chart-Umschaltung zwischen Kerzen und Linie
- schnelle Timeframe-Schalter fuer 1d, 1wk und 1mo
- Energiesparmodus mit manuellen Analysen und Cache-Zeiten pro Timeframe
- Pink-Alerts fuer Breakouts, EMA-Cross, Relative-Staerke-Wechsel und Marktstatus-Wechsel
- lokale Alert-Historie in `data/workspace.duckdb`
- Backtesting fuer einfache Setup-Regeln, historische Score-Pruefung und Signal-Auswertung
- gespeicherte Chart-Linien fuer Unterstuetzung, Widerstand und Trendlinien
- Schnelllinien fuer Close, Support, Widerstand und Trend 30
- eigene Watchlists mit Kategorien, Pins und Sortierung nach Score, Trend oder Risk State
- Hauptliste mit Indizes, Gold, Mag7, Plus-Button und manueller Reihenfolge
- Papertrading-Journal mit Analyse-Snapshots
- Papertrading-Lernsystem mit Entry, Stop, Ziel, Setup und automatischen Regelverletzungen
- Papertrading-Auswertung mit Equity Curve, Max Drawdown, Trefferquote, Ø Gewinn/Verlust und Setup-Kategorien
- Real-Money-Journal fuer manuelle Depot-Spiegelung
- Broker-Planung mit Provider-Matrix fuer spaetere Anbindungen
- Trading-Safety-Gate mit Sandbox-Pflicht, Vorschau, 2-Klick-Freigabe, Kill-Switch und Audit-Log
- Login mit E-Mail, Passwort und Zwei-Faktor-Code
- extra Passwort-Gate fuer Settings, Updates, Ports und API-Platzhalter
- Rate-Limits fuer Registrierung, Passwort, E-Mail-Code und 2FA
- Timeframes: 1d, 1wk, 1mo
- EMA20, EMA50, EMA100, EMA200
- regelbasiertes Risk Management: `OK`, `REDUCED`, `BLOCKED`
- Score-Modell `sensei_chain_v2`: SPY, QQQ, Markt-Bestaetigung, Mag7, Sektor-Staerke, relative Staerke, Trendfolge
- feste Reports: `market_summary.csv`, `watchlist.csv`, `evening_summary.txt`
- vorbereiteter Modus-Schalter: `papertrading` oder `real`

Der Modus-Schalter ist nur Vorbereitung. Auch im Modus `real` bleiben Orders,
Broker und echte Ausfuehrung deaktiviert.

## Papertrading und Real Money

Die App hat zwei getrennte Tracking-Bereiche:

- `Papertrading`: simulierte Eintraege, die parallel zur Analyse mitlaufen.
- `Real Money`: manuelle Dokumentation echter Positionen ohne Broker-Verbindung.

Beim Speichern eines Eintrags werden der aktuelle Analyse-Score, Trend, Risk
State, relative Staerke, Setup-Kategorie und markierte Regelverletzungen
gesichert. Bei jeder neuen Analyse schreibt die App Snapshots fuer offene
Eintraege. Dadurch entsteht ein lokaler Verlauf mit Marktwert, offenem P/L und
aktuellem Risk State.

Das Papertrading ist als Lernsystem aufgebaut. Jeder Eintrag speichert Entry,
Stop, Ziel, Setup-Kategorie und These. Beim Speichern markiert die App
Regelverletzungen automatisch, zum Beispiel fehlenden Stop, fehlendes Ziel,
Score unter Mindestwert, BLOCKED Risk State, Trend gegen Richtung, Close unter
EMA200, Marktampel nicht OK oder fehlende These. Manuelle Zusatzmarkierungen
sind weiterhin moeglich.

Moegliche Aktionen:

- neuen Eintrag erfassen
- offenen Eintrag schliessen
- Equity Curve anzeigen
- Max Drawdown messen
- Trefferquote, durchschnittlichen Gewinn und durchschnittlichen Verlust sehen
- Setup-Kategorien auswerten
- Regelverletzungen zaehlen
- Papertrading gegen Real Money vergleichen
- Journal als CSV herunterladen
- Export nach `reports/papertrading_journal.csv`
- Export nach `reports/real_money_journal.csv`

Auch diese Bereiche fuehren nichts aus. Sie sind Journal, Simulation und
Auswertung, keine Ordermaske.

## Backtesting

Der Bereich **Backtesting** testet einfache, transparente Regeln auf bereits
geladenen historischen Daten. Es werden keine Daten bei jedem Klick neu geladen
und es werden keine Orders erzeugt.

Getestet werden koennen:

- `Trendfolge`
- `Breakout`
- `Pullback`
- `Relative Staerke`

Der Backtest nutzt eine historische Score-Naehierung nach den Kernregeln:
SPY-Trend, QQQ-Trend, SPY/QQQ-Bestaetigung, Kurs ueber EMA20/50/100/200 und
relative Staerke gegen QQQ oder SPY. Die Auswertung zeigt:

- Ergebnis pro Setup-Kategorie
- Score-Buckets rueckwirkend
- Trefferquote, Durchschnittsreturn, Gewinner/Verlierer
- Backtest Equity Curve und Drawdown
- konkrete Signale, die funktioniert oder nicht funktioniert haetten
- CSV-Download der Backtest-Signale

Das ist nur Analyse. Es gibt keine echten Orders, keine Broker-Funktion und
keine Ausfuehrung.

## Broker-Planung

In den vorbereiteten Trade-Tickets und im Settings-Tab gibt es eine
Provider-Matrix fuer spaetere Integrationen. Enthalten sind grosse Anbieter fuer
Aktien, ETFs, Indizes, Forex und Krypto, unter anderem Interactive Brokers,
Alpaca, Tradier, Saxo, Kraken, Coinbase Advanced, Binance und IG.

Die App nutzt diese Matrix nur fuer Planung, Journal-Notizen und Statusanzeige:

- empfohlener Provider je Symbol
- erkannte Asset-Klasse
- Hinweis, ob der Provider spaeter sinnvoll waere
- Sicherheitsstatus: keine Ausfuehrung, keine API-Calls

Auch hier gilt: Es gibt keine echte Verbindung, keine Orderausfuehrung und keine
Broker-Aktion. Der naechste sinnvolle Entwicklungsschritt waere ein reiner
Paper-Adapter mit Mock-Fills, bevor irgendeine echte Schnittstelle angebunden
wird.

## Trading Safety

Vor einer spaeteren echten Broker-Anbindung liegt ein hartes Safety-Gate:

- zuerst nur Sandbox/Paper-API
- Order-Vorschau ist Pflicht
- 2-Klick-Bestaetigung ist Pflicht
- harte manuelle Freigabe ist Pflicht
- Kill-Switch bleibt aktiv
- Tagesverlustlimit ist aktiv
- Audit-Log schreibt sicherheitsrelevante Ereignisse nach
  `logs/trading_safety_audit.jsonl`
- automatische Orders sind nicht erlaubt

Die Settings zeigen diese Checkliste und erlauben nur Safety-Limits sowie
Audit-Testeintraege. Live-Trading, Broker-API und automatische Ausfuehrung
bleiben deaktiviert.

## Heute Ansehen

Die Startseite **Heute ansehen** ist fuer den schnellen Tagesblick gebaut:

- oben: **Was ist heute wichtig?**
- klare Ampel: `Markt OK`, `Vorsicht` oder `Blockiert`
- Top-Kandidaten als Karten statt breiter Tabellen
- schnelle Buttons: `Analysieren`, `Top Chart`, `Screen speichern`, `Workspace`
- gespeicherte Themen und Screens koennen mit einem Klick geoeffnet werden

Die Seite nutzt vorhandene Analyse- und Cache-Daten. Keine Orders, keine
Broker-Aktion.

## Workspace

Der Workspace ist die zweite, detailliertere Arbeitsflaeche der App. Er ist wie
eine kleine, vereinfachte TradingView-Arbeitsflaeche aufgebaut:

- Startbereich **Heute ansehen** mit Marktampel
- mobile Schnellansicht: Watchlist zuerst, Chart darunter
- Pink als feste Alert-Farbe fuer System-Erkennung, Speicherung und Breakout-Watch
- Ampel-Logik: `Markt OK`, `Vorsicht`, `Blockiert`
- klare Aktionen: `Analysieren`, `Speichern`, `Beobachten`
- Ticker und Timeframe waehlen
- Score, Trend, Risk State und EMAs im Schnellblick sehen
- echte OHLC-Kerzen mit Volumen ansehen
- EMA20, EMA50, EMA100 und EMA200 direkt im Chart sehen
- Zoom und Pan im Chart nutzen
- temporaere Linien direkt im Plotly-Chart zeichnen
- dauerhafte Linien mit Start/Ende/Preis speichern
- gespeicherte Linien pro Symbol und Timeframe automatisch wieder laden
- Schnelllinien fuer Close, Support, Widerstand und 30-Kerzen-Trend setzen
- Dashboard-Chart als Vollbild-Arbeitsflaeche oeffnen
- Symbole per Schnellbutton wechseln
- eigene Watchlists pflegen und daraus den Fokus setzen
- Thema mit Name, Kategorie und Notiz speichern
- gespeicherte Themen direkt wieder oeffnen
- mit **Analysieren** bewusst eine volle Analyse plus Reports starten

Der Schnellblick nutzt die bereits geladene Analyse und spart damit Energie.
Eine volle Datensammlung passiert nur beim Start, bei Analyse-Buttons oder bei
der Abendanalyse.

## Dashboard Launch-Check

Der erste Dashboard-Screen ist auf diese Pflichtpunkte ausgelegt:

- Dark Mode als Standard
- TradingView-artige Arbeitsflaeche ohne Marken-Kopie
- grosse Marktkarten fuer SPY, QQQ, GLD und DAX
- Score-Karten mit Elite/A/B/Beobachten-Farben
- Top 5 Chancen sichtbar im Dashboard
- Marktstatus mit Ampel-Logik
- Alerts in Pink fuer System-Erkennung und Breakout-Watch
- responsive Layouts fuer Desktop und iPhone-Vorbereitung

## Prompt-Checks

Die drei aktuellen Launch-Prompts sind im Projekt abgedeckt:

- **UI modernisieren**: dunkles Dashboard, TradingView-artiger Aufbau, grosse
  Marktkarten, Score-Karten, Top 5 Chancen, Marktstatus, Alerts und responsive
  Layouts.
- **Duplicate Keys global fixen**: `scripts/check_streamlit_keys.py` prueft
  alle wichtigen Streamlit-Widgets in `app.py` und `modules/` auf eindeutige
  Keys. Der Check laeuft automatisch ueber `scripts/check_project.sh`.
- **Backup + Update System**: Updates laufen nur lokal, nur aus `updates/`,
  nur fuer `app.py`, `config.json` und `modules/*.py`. Vor jedem Update wird
  automatisch ein Backup erstellt. Symlinks, falsche Dateitypen und dynamische
  Code-Ausfuehrung werden blockiert.

## Mobile Ansicht

Die mobile Nutzung ist auf kurze Wege ausgelegt:

- kompakte Karten statt Tabellen als erste Ansicht
- Watchlist oben in der **Mobile Schnellansicht**
- Chart direkt unter der Watchlist
- breite Tabellen bleiben in einklappbaren Details
- Papertrading und Real Money zeigen erst Kennzahlen; Performance, Eintrag,
  Schliessen und Journal sind eingeklappt

## UI-Systemfarbe Pink

Die Oberflaeche orientiert sich an einer kompakten Analyse-/Charting-App:
Watchlist, Timeframes, Chart und Alerts stehen nah beieinander. Pink ist dabei
die feste Systemfarbe fuer:

- System-Erkennung
- Breakout erkannt
- EMA-Cross erkannt
- Relative-Staerke-Wechsel
- Marktstatus-Wechsel von OK zu Vorsicht oder Blockiert
- Breakout-Watch
- Momentum-Alert
- Relative-Staerke-Hinweise
- Speicherung von Beobachtungen, Themen und Linien
- vorbereitende Bot-/Alert-Datenpunkte

Neue oder geaenderte Alert-Zustaende werden lokal in der Alert-Historie
gespeichert. Die App nutzt dafuer nur Analyse- und Chartdaten, keine Order- oder
Broker-Funktion.

Pink bedeutet nicht Order, Broker-Aktion oder Ausfuehrung. Die App bleibt
Analyse-only.

## Energiesparmodus

Die App ist auf sparsames Laden ausgelegt:

- Beim Start werden nur Kernmaerkte und Watchlist geladen.
- Die groessere Sektorrotation wird erst bei manueller Analyse oder im Tab
  **Sektorrotation** geladen.
- Danach werden Daten nur ueber **Analysieren** oder die lokale Abendanalyse neu geladen.
- Settings, Moduswechsel, Watchlist-Pflege und Navigation starten keine Vollanalyse.
- Frischer Cache wird vor yfinance genutzt.
- Wenn yfinance keine Daten liefert, kann optional `ALPHA_VANTAGE_API_KEY`
  als zweite echte Datenquelle genutzt werden.
- Jede Analysezeile zeigt `data_status`, `data_source`, `last_clean_date`
  und eine klare `data_message`.
- Cache-Zeiten stehen in `config.json` unter `data.cache_max_age_hours`:
  `1d = 6h`, `1wk = 24h`, `1mo = 72h`.
- Tracking-Snapshots werden nur nach Analyse, Speichern oder Schliessen eines Eintrags geschrieben.
- Geplante Hintergrundjobs laufen nur lokal. Im Cloud-Modus wird nur beim Start oder Button-Klick geladen.

## Datenqualitaet

Die App unterscheidet Daten sichtbar nach Status:

- `live`: vorbereitet fuer eine direkte Live-Datenquelle, aktuell nicht aktiv.
- `delayed`: echte, aber verzoegerte Marktdaten von `yfinance` oder optional `alpha_vantage`.
- `cache`: lokale Daten aus dem Cache, wenn sie innerhalb der Cache-Regeln genutzt werden.
- `fehlerhaft`: keine echten Daten verfuegbar. Die App bleibt stabil, markiert die Daten aber klar als nicht sauber.

Optionaler zweiter Provider:

- Lokal: `export ALPHA_VANTAGE_API_KEY=\"dein-key\"`
- Streamlit Cloud: Secret `ALPHA_VANTAGE_API_KEY = \"dein-key\"` setzen.

Der Key wird nicht in `config.json` gespeichert. Ohne Key nutzt die App weiter
yfinance plus Cache und markiert fehlende echte Daten als `fehlerhaft`.

## Eigene Watchlists

Neben der festen Mag7-Ansicht kannst du eigene Watchlists anlegen:

- Kategorien: `Indizes`, `Aktien`, `Gold`, `Krypto`, `Eigene Ideen`
- Symbole hinzufuegen und entfernen
- Favoriten/Pins setzen
- automatische Sortierung nach `Score`, `Trend`, `Risk State` oder Pins
- eigene Watchlist bewusst analysieren, damit neue Ticker Scores bekommen

Neue Watchlist-Symbole bleiben lokal in `data/workspace.duckdb` gespeichert.
Die App fuehrt auch hier keine Orders und keine Broker-Aktionen aus.

## Dashboard-Startansicht

Das Dashboard startet mit einer kompakten Arbeitsflaeche:

- **Market Summary** fuer Hauptmaerkte: Durchschnittsscore, Marktstatus, Bullish/Neutral/Bearish, OK/Reduced/Blocked, Top/Weak Symbol
- **Watchlist Summary** fuer deine Watchlist: dieselben Kennzahlen plus positive relative Staerke
- links die **Hauptliste** mit SPY, SPX500, QQQ, Nasdaq100, GLD, Gold, DAX und Mag7
- rechts direkt der Chart des angeklickten Symbols
- im Vollbildmodus Symbol-Schnellwechsel ohne Rueckweg zur linken Watchlist
- gespeicherte Linien werden je Symbol und Timeframe wieder geladen
- Plus-Bereich zum Speichern weiterer Indizes, Aktien, Krypto- oder Rohstoffsymbole
- Hoch/Runter-Buttons fuer deine eigene Reihenfolge
- Charttyp-Umschaltung zwischen `Kerzen` und `Linie`
- Plotly-Zeichenwerkzeuge im Chart fuer schnelle visuelle Markierungen
- Schnelllinien und gespeicherte Linienverwaltung unter dem Chart
- Hauptsystem-Werkzeugleiste unter dem Chart fuer Hintergrund-Setups

Auf kleinen Displays stapelt Streamlit die linke Watchlist ueber den Chart.
Damit bleibt die Bedienung fuer iPhone vorbereitet, ohne eine zweite App-Ansicht
pflegen zu muessen.

## Sektorrotation

Die Rubrik **Sektorrotation** ist eine eigene Analyse-Watchlist fuer Maerkte,
keine Einzelaktien. Ziel ist zu sehen, wohin Kapital relativ zum S&P 500
wandert:

- breite Maerkte: SPY, QQQ, IWM
- US-Sektoren: XLK, XLF, XLI, XLY, XLP, XLV, XLE, XLU, XLB, XLRE, XLC
- Bau/Infrastruktur: XHB, PAVE
- Themen: SMH
- Rohstoffe/Krypto: GLD, USO, BTC-USD
- Makro: US Dollar Index `DX-Y.NYB`
- Treasuries: SHY, IEI, IEF
- Treasury Yields: `^FVX`, `^TNX`

Die Auswertung zeigt Kapitalfluss, Risk-On/Risk-Off, Score, Trend, relative
Staerke gegen SPY und eine TradingView-artige Score-Heatmap. Feste
Vergleichsgruppen zeigen Tech, Finance, Bau, Energie, Gold, Dollar und
Treasuries nebeneinander. Zusaetzlich werden Veraenderungen gegenueber gestern,
woechentlich und monatlich angezeigt.

Die Watchlist kann in der Rubrik erweitert werden. Auch hier gilt: keine
Orders, keine Broker-Aktion, nur Analyse.

## Hauptsystem-Werkzeugleiste

Unter dem Chart liegt eine Werkzeugleiste fuer Setups, die im Hintergrund
berechnet werden. Standardmaessig sind sie optisch aus. Erst wenn ein Schalter
aktiviert wird, zeichnet die App das jeweilige Setup in den Chart:

- Beobachtung
- Fibonacci
- Alligator
- Order Blocks
- Breakouts
- Tick-Waves
- Volumen
- Monat Aufstieg
- Monat Abstieg

Diese Werkzeuge erweitern die Analyse-, Backtest- und Bewertungsgrundlage. Sie
sind keine Order-Signale und fuehren keine Aktionen aus.

## Score-Logik

Das Bewertungssystem folgt der Analyse-Kette `sensei_chain_v2`:

1. SPY Trend: 15 Punkte
2. QQQ Trend: 15 Punkte
3. SPY + QQQ Bestaetigung: 15 Punkte
4. Mag7-Breite: 15 Punkte
5. Sektor-Staerke: 15 Punkte
6. Relative Staerke gegen QQQ: 10 Punkte
7. Trendfolge ueber EMA-Struktur: 15 Punkte

Die App speichert die Einzelpunkte in den Analyse- und Reportdaten. Alte
EMA-Spalten bleiben aus Kompatibilitaetsgruenden vorhanden, aber der Hauptscore
folgt der neuen Kette.

## Schnellstart

```bash
cd "analyse-market-sensei-cut"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
streamlit run app.py
```

## Desktop-Nutzung

Auf dem Desktop liegen zwei Starter:

- `Analyse Market Sensei Cut starten.command`
- `Analyse Market Sensei Cut stoppen.command`

Starten:

1. Doppelklick auf `Analyse Market Sensei Cut starten.command`
2. Browser oeffnet `http://localhost:8501`
3. In der App registrieren
4. Passwort selbst erstellen
5. Bestaetigungscode eingeben
6. Einloggen
7. Zwei-Faktor-Code eingeben

Im lokalen Desktop-Modus wird kein Online-SMTP benoetigt. Wenn kein Mailserver
konfiguriert ist, zeigt die App den Bestaetigungscode direkt nach der
Registrierung an.

Optional lokal mit Environment:

```bash
APP_ENV=local streamlit run app.py
```

Cloud-Modus lokal simulieren:

```bash
APP_ENV=cloud APP_PASSWORD=test streamlit run app.py
```

## Check

```bash
cd "analyse-market-sensei-cut"
./scripts/check_project.sh
./scripts/security_check.sh
```

## Online-MVP auf Streamlit Community Cloud

Deployment-Dateien:

- `app.py` als Streamlit Entry Point
- `requirements.txt` fuer Python-Pakete
- `runtime.txt` mit `python-3.11`
- `config.json`
- `modules/`
- `main.py`
- `version.json`

Secrets in Streamlit Community Cloud:

```toml
APP_ENV = "cloud"
APP_PASSWORD = "<starkes-app-passwort>"
AUTH_ALLOWED_EMAILS = "deine-mail@example.com"

SMTP_HOST = "smtp.example.com"
SMTP_PORT = "587"
SMTP_USERNAME = "smtp-user"
SMTP_PASSWORD = "<smtp-password>"
SMTP_FROM = "Analyse Market Sensei Cut <noreply@example.com>"
SMTP_USE_TLS = "true"

EXAMPLE_API_KEY = "<api-key>"
```

## Online-Betrieb

Die App hat einen eigenen Bereich **Online-Betrieb**:

- Secrets-Status ohne Anzeige echter Werte
- Health-Check fuer Version, Logs, Reports, Data und Cloud-Sperren
- Monitoring-Log in `logs/online_ops.jsonl`
- Fehlerlog-Auszug aus App-, Update-, Evening- und Safety-Logs
- Cloud-Backup als JSON fuer Konfig-Auswahl, Watchlists und gespeicherte Themen
- Restore aus einem Cloud-Backup per Upload
- Deploy-Check lokal per Script

Wichtig: In Streamlit Community Cloud sind lokale Update-, Rollback- und
Shell-Funktionen deaktiviert. Code-Aenderungen laufen ueber GitHub-Deploy.
Der Cloud-Speicher ist nicht dauerhaft garantiert, deshalb regelmaessig im
Bereich **Online-Betrieb** ein JSON-Backup herunterladen.

Lokale Deploy-Routine:

```bash
./scripts/prepare_cloud_deploy.sh
```

Das Script fuehrt Projektcheck, Security-Check, lokalen Smoke-Test,
Cloud-Smoke-Test und einen sauberen Upload-Zip-Check aus. Secrets werden nicht
in das Zip aufgenommen.

Cloud-Verhalten:

- Vor jedem Login verlangt die App `APP_PASSWORD`
- Anmeldung laeuft ueber E-Mail, Passwort und Bestaetigungscode
- Login verlangt zusaetzlich einen Zwei-Faktor-Code
- Registrierung ist im Cloud-Modus ohne `AUTH_ALLOWED_EMAILS` blockiert
- SMTP-Secrets sind fuer echte Mail-Bestaetigung erforderlich
- Update-System ist deaktiviert
- Rollback ueber UI ist deaktiviert
- LaunchAgent/macOS-Buttons sind ausgeblendet
- lokale Shell-Skripte werden nicht ausgefuehrt
- Power-Check wird ignoriert
- Online-Betrieb zeigt Secrets nur als Status `gesetzt/fehlt`
- Cloud-Backup laeuft als Download/Upload-JSON fuer Konfig und Watchlists
- Reports und DuckDB werden nur als temporaere Laufzeitdateien betrachtet

Deployment-Schritte:

1. Nur diesen Projektordner in ein GitHub-Repo legen.
2. Lokal `./scripts/prepare_cloud_deploy.sh` ausfuehren.
3. Keine lokalen Laufzeitdaten committen (`data/`, `reports/`, `logs/`, `backups/`, `.venv/` sind ignoriert).
4. Auf Streamlit Community Cloud eine App aus dem GitHub-Repo erstellen.
5. Entry Point auf `app.py` setzen.
6. In Advanced settings Python 3.11 waehlen oder `runtime.txt` verwenden.
7. Secrets eintragen.
8. Deploy starten.
9. In der App **Online-Betrieb** oeffnen und Secrets, Health, Logs und Backup pruefen.

## Anmeldung und Identitaet

Die App hat eine vorbereitete E-Mail-Identitaet:

- Registrierung mit E-Mail und Passwort
- Passwort-Hashing mit PBKDF2
- E-Mail-Bestaetigung per 6-stelligem Code
- Zwei-Faktor-Code beim Login
- Rate-Limits gegen Brute Force und Code-Spam
- optional eingeschraenkte Registrierung via `AUTH_ALLOWED_EMAILS`
- vorbereitete Passkey/WebAuthn-Tabelle `passkey_credentials`

Passkeys sind vorbereitet, aber noch nicht aktiv. Fuer echte Passkeys braucht die
App eine HTTPS-Domain und eine WebAuthn-Komponente. Das ist der naechste
Ausbauschritt nach dem sicheren MVP.

Wichtig fuer Streamlit Community Cloud: Die lokale DuckDB-Datei fuer Nutzer kann
bei Neustart oder Redeploy verloren gehen. Fuer dauerhafte Identitaeten sollte
spaeter eine externe Datenbank angebunden werden.

## Geschuetzte Einstellungen, Ports und APIs

Nach dem Login sind Settings und Updates zusaetzlich per Passwort-Gate
geschuetzt. Du musst dein Account-Passwort erneut eingeben, bevor sensible
Konfigurationen sichtbar werden.
Die Entsperrung laeuft automatisch nach `sensitive_unlock_minutes` ab.

Im Settings-Tab gibt es den Bereich **Ports, Seitenlinks und APIs**:

- `streamlit_port`: vorbereiteter App-Port, Standard `8501`
- `local_api_port`: optionaler lokaler API-Port
- `webhook_port`: optionaler Webhook-Port
- `protected_links`: passwortgeschuetzte Seitenlinks
- `protected_apis`: passwortgeschuetzte API-Platzhalter

API-Keys sollen nicht in `config.json` stehen. Trage in der App nur den
Secret-Namen bei `api_key_secret_ref` ein, z.B. `MY_DATA_API_KEY`. Den echten
Wert legst du in Streamlit Secrets oder als Umgebungsvariable ab.

Die App fuehrt aus diesen API-Platzhaltern keine Requests aus. Sie speichert nur
die geschuetzte Konfiguration.

## Risk Management

Das Risk Management ist rein regelbasiert und fuehrt keine Orders aus.

Zustaende:

- `OK`: harte Regeln bestanden
- `REDUCED`: Analyse erlaubt, Risiko reduziert
- `BLOCKED`: Analyseobjekt gesperrt

Harte BLOCKED-Regeln:

- Score unter 40
- Symboltrend bearish
- Close unter EMA200
- SPY und QQQ beide bearish

REDUCED-Regeln:

- Score unter 60
- Close unter EMA20 oder EMA50
- relative Staerke gegen QQQ negativ
- SPY und QQQ nicht gleiche Richtung

Limits stehen in `config.json` unter `risk_management`. Sie sind Analysewerte,
keine Ordergroessen und keine Handelsempfehlungen.

## Launch-Checkliste

- GitHub-Repo nur mit diesem Projektordner erstellen
- `./scripts/check_project.sh` lokal ausfuehren
- optional `pip-audit -r requirements.txt` ausfuehren
- Streamlit Cloud App mit `app.py` als Entry Point deployen
- `APP_ENV = "cloud"` setzen
- `APP_PASSWORD` als starkes App-Passwort setzen
- SMTP-Secrets setzen
- `AUTH_ALLOWED_EMAILS` auf deine E-Mail setzen
- in **Online-Betrieb** pruefen, dass alle Pflicht-Secrets gesetzt sind
- App-Passwort-Gate testen
- Registrierung testen
- E-Mail-Code bestaetigen
- Login testen
- 2FA-Code testen
- Settings-Passwort-Gate testen
- Disclaimer sichtbar pruefen

Weitere Details stehen in `SECURITY.md`.

## Update-System

Neue Code-Dateien koennen in `updates/` gelegt und im Tab **Updates** geprueft
und angewendet werden.

Erlaubt sind nur:

- `updates/app.py`
- `updates/config.json`
- `updates/modules/*.py`

Vor jedem angewendeten Update erstellt die App automatisch ein Backup in
`backups/YYYY-MM-DD_HH-MM-SS/`. Rollback kopiert das letzte Backup zurueck.

Nach einem Update wird `version.json` erhoeht und `logs/changelog.txt`
erweitert. Fehler stehen in `logs/update_log.txt`.

## Evening Analysis

Manuell:

```bash
python main.py --mode evening-analysis
```

Oder in der App im Dashboard ueber **Abendanalyse jetzt starten**.

Geplanter macOS Job:

```bash
./install_evening_job.sh
./uninstall_evening_job.sh
```

Der LaunchAgent startet taeglich um 22:30 Uhr. Vor der Analyse prueft
`modules/power_check.py`, ob der Mac am Netzteil haengt. Wenn nicht, wird in
`logs/evening_analysis.log` protokolliert und die Analyse abgebrochen.

Im Cloud-Modus ist der macOS LaunchAgent ausgeblendet. Die CLI funktioniert
weiterhin; `APP_ENV=cloud` ignoriert den Power-Check.

## Wichtiger Hinweis

Dieses Projekt ist kein Finanzrat. Die Scores sind technische Analysewerte und
keine Kauf- oder Verkaufsempfehlungen.
