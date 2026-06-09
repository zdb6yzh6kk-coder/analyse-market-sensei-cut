# Analyse Market Sensei Cut

Eine Streamlit-App fuer einfache Marktdatenanalyse. Sie laeuft lokal auf dem Mac
und ist fuer einen sicheren MVP-Launch auf Streamlit Community Cloud vorbereitet.

Die App fuehrt keine Orders aus, enthaelt keine Broker-Anbindung und ist kein
Trading-System. Sie zeigt Trends, Scores, relative Staerke und CSV-Reports.

## Status

- Streamlit Dashboard
- yfinance Marktdaten mit lokalem Fallback
- DuckDB Speicherung
- Plotly Charts
- Dashboard, Watchlist, Reports, Updates und Settings
- Workspace mit Schnellblick, gespeicherten Themen und Datensammlung
- Candlestick-Chart mit EMA20/50/100/200 und Volumen
- schnelle Timeframe-Schalter fuer 1d, 1wk und 1mo
- Energiesparmodus mit manuellen Analysen und Cache-Zeiten pro Timeframe
- gespeicherte Chart-Linien fuer Unterstuetzung, Widerstand und Trendlinien
- eigene Watchlists mit Kategorien, Pins und Sortierung nach Score, Trend oder Risk State
- Papertrading-Journal mit Analyse-Snapshots
- Papertrading-Auswertung mit Equity Curve, Drawdown, Trefferquote und Setup-Kategorien
- Real-Money-Journal fuer manuelle Depot-Spiegelung
- Login mit E-Mail, Passwort und Zwei-Faktor-Code
- extra Passwort-Gate fuer Settings, Updates, Ports und API-Platzhalter
- Rate-Limits fuer Registrierung, Passwort, E-Mail-Code und 2FA
- Timeframes: 1d, 1wk, 1mo
- EMA20, EMA50, EMA100, EMA200
- regelbasiertes Risk Management: `OK`, `REDUCED`, `BLOCKED`
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

## Workspace

Der Workspace ist die einfache Startseite der App. Er ist wie eine kleine,
vereinfachte TradingView-Arbeitsflaeche aufgebaut:

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
- Symbole per Schnellbutton wechseln
- eigene Watchlists pflegen und daraus den Fokus setzen
- Thema mit Name, Kategorie und Notiz speichern
- gespeicherte Themen direkt wieder oeffnen
- mit **Analysieren** bewusst eine volle Analyse plus Reports starten

Der Schnellblick nutzt die bereits geladene Analyse und spart damit Energie.
Eine volle Datensammlung passiert nur beim Start, bei Analyse-Buttons oder bei
der Abendanalyse.

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
- Breakout-Watch
- Momentum-Alert
- Relative-Staerke-Hinweise
- Speicherung von Beobachtungen, Themen und Linien
- vorbereitende Bot-/Alert-Datenpunkte

Pink bedeutet nicht Order, Broker-Aktion oder Ausfuehrung. Die App bleibt
Analyse-only.

## Energiesparmodus

Die App ist auf sparsames Laden ausgelegt:

- Beim Start wird einmal geladen.
- Danach werden Daten nur ueber **Analysieren** oder die lokale Abendanalyse neu geladen.
- Settings, Moduswechsel, Watchlist-Pflege und Navigation starten keine Vollanalyse.
- Frischer Cache wird vor yfinance genutzt.
- Cache-Zeiten stehen in `config.json` unter `data.cache_max_age_hours`:
  `1d = 6h`, `1wk = 24h`, `1mo = 72h`.
- Tracking-Snapshots werden nur nach Analyse, Speichern oder Schliessen eines Eintrags geschrieben.
- Geplante Hintergrundjobs laufen nur lokal. Im Cloud-Modus wird nur beim Start oder Button-Klick geladen.

## Eigene Watchlists

Neben der festen Mag7-Ansicht kannst du eigene Watchlists anlegen:

- Kategorien: `Indizes`, `Aktien`, `Gold`, `Krypto`, `Eigene Ideen`
- Symbole hinzufuegen und entfernen
- Favoriten/Pins setzen
- automatische Sortierung nach `Score`, `Trend`, `Risk State` oder Pins
- eigene Watchlist bewusst analysieren, damit neue Ticker Scores bekommen

Neue Watchlist-Symbole bleiben lokal in `data/workspace.duckdb` gespeichert.
Die App fuehrt auch hier keine Orders und keine Broker-Aktionen aus.

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
- Reports und DuckDB werden nur als temporaere Laufzeitdateien betrachtet

Deployment-Schritte:

1. Nur diesen Projektordner in ein GitHub-Repo legen.
2. Keine lokalen Laufzeitdaten committen (`data/`, `reports/`, `logs/`, `backups/`, `.venv/` sind ignoriert).
3. Auf Streamlit Community Cloud eine App aus dem GitHub-Repo erstellen.
4. Entry Point auf `app.py` setzen.
5. In Advanced settings Python 3.11 waehlen oder `runtime.txt` verwenden.
6. Secrets eintragen.
7. Deploy starten.

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
