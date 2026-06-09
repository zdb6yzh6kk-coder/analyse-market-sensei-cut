# Security Checklist

## Vor dem Cloud-Launch

- `APP_ENV = "cloud"` in Streamlit Secrets setzen.
- `APP_PASSWORD` als starkes App-Passwort in Streamlit Secrets setzen.
- `AUTH_ALLOWED_EMAILS` auf deine erlaubten E-Mail-Adressen setzen.
- SMTP-Secrets vollstaendig setzen, sonst ist Cloud-Registrierung blockiert.
- Keine echten API-Keys in `config.json` speichern.
- API-Keys nur als Streamlit Secrets oder Umgebungsvariablen ablegen.
- `data/`, `reports/`, `logs/`, `backups/`, `updates/` nicht committen.
- `./scripts/check_project.sh` ausfuehren.
- Dependency-Audit mit `pip-audit -r requirements.txt` ausfuehren.

## Aktive Schutzmechanismen

- E-Mail-Registrierung mit Bestaetigungscode.
- App-Passwort-Gate vor der Benutzeranmeldung.
- Login mit Passwort und Zwei-Faktor-Code.
- Rate-Limits fuer Passwort, Registrierung, Verifizierung und 2FA.
- Settings und Updates sind nach Login zusaetzlich passwortgeschuetzt.
- Sensible Entsperrung laeuft nach `sensitive_unlock_minutes` ab.
- Update-System ist im Cloud-Modus deaktiviert.
- macOS LaunchAgent und lokale Shell-Skripte sind im Cloud-Modus deaktiviert.
- API-Platzhalter speichern nur Secret-Namen und fuehren keine Requests aus.
- Orders, Broker und echte Ausfuehrung bleiben deaktiviert.

## Rest-Risiken

- Streamlit Community Cloud ist kein dauerhafter Datenbank-Host. Fuer produktive
  Nutzerkonten sollte spaeter eine externe Datenbank angebunden werden.
- E-Mail-Code-2FA ist solide fuer einen MVP, aber Passkeys/WebAuthn waeren der
  bessere naechste Schritt fuer eine feste HTTPS-Domain.
- Lokale Update-Dateien duerfen Code ersetzen. Dieses Feature nur lokal und nur
  mit vertrauenswuerdigen Dateien verwenden.
