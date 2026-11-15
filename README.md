# IKHP Tävlingsportal – serverbaserad utvecklingsversion

## Starta lokalt
Kräver Python 3.10 eller senare. Inga extra Python-paket behövs.

**Windows PowerShell:**
```powershell
$env:IKHP_ADMIN_PASSWORD="välj-ett-starkt-adminlösenord"
$env:IKHP_CLUB_PASSWORD="välj-ett-gemensamt-klubblösenord"
$env:IKHP_BANKGIRO="ange-riktigt-bankgiro"
python server.py
```
Öppna http://localhost:8080.

**macOS / Linux:**
```bash
export IKHP_ADMIN_PASSWORD='välj-ett-starkt-adminlösenord'
export IKHP_CLUB_PASSWORD='välj-ett-gemensamt-klubblösenord'
export IKHP_BANKGIRO='ange-riktigt-bankgiro'
python3 server.py
```

## Automatisk e-post
Sätt `SMTP_HOST`, `SMTP_PORT` (standard 587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.
Servern använder STARTTLS som standard; sätt `SMTP_SSL=true` och `SMTP_PORT=465` för implicit TLS.
När anmälan registreras försöker servern skicka ett bekräftelsemejl. Resultatet (`sent` eller `failed`) sparas i databasen och visas i adminhistoriken. Om SMTP inte är konfigurerat sparas anmälan men inget mejl skickas.

## Officiell anmälningsstatus
Administratören kan manuellt markera en anmälan som officiellt registrerad. Detta loggas i `audit`.
Knappen **Bekräfta och skicka in** är avstängd tills `IKHP_EXTERNAL_API_URL` och `IKHP_EXTERNAL_API_TOKEN` har konfigurerats för en *verifierad och behörig* adapter.
Adaptern ska acceptera HTTP POST JSON, `Authorization: Bearer <token>` och `Idempotency-Key`. Den måste returnera JSON i formen `{"status":"confirmed","reference":"extern-id"}` för att portalen ska markera anmälan som bekräftad. Detta är **inte** en färdig koppling till EasyRecord, Track and Field, Webathletics eller Friidrottsanmälan.

## Historik
Historikknappen visas endast efter administratörsinloggning. Historikens API kräver dessutom giltig administratörssession; ett direktanrop utan session ger 403. Inloggningen använder en serverlagrad sessionsnyckel i en HttpOnly-cookie.

## Viktigt inför produktionsdrift
- Använd HTTPS och sätt `IKHP_HTTPS=1` för Secure-cookie.
- Lägg till CSRF-skydd, inloggningsbegränsning, sessionstidsgräns, backup och robust e-postkö innan offentlig driftsättning.
- Kör bakom en riktig webbserver/reverse proxy; `http.server` är avsett för utveckling, inte produktion.
- Säkerställ GDPR-rutiner och rättslig grund för offentlig publicering av barns namn, klass och grenar.
- För närvarande stöds manuell tävlingsregistrering; externa tävlingsimporter är inte implementerade.
- Gemensamt klubb-lösenord lagras hashat i SQLite. Administratörslösenordet anges via miljövariabel. Varken lösenord eller SMTP-uppgifter ska läggas i källkoden.
- Bankgiro måste sättas till IKHP:s riktiga bankgiro innan användning.
- Åldersklassfiltreringen är en förenklad modell som ska valideras mot respektive tävlings regelverk.
