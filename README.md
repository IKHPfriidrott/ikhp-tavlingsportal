# IKHP Tävlingsportal – Render testmiljö

**Det här paketet är endast för test med påhittade uppgifter.** Det är inte en produktionslösning för föreningens personuppgifter.

## 1. Publicera på Render (enklaste vägen)
1. Skapa ett **privat** repository på GitHub och ladda upp filerna i den här ZIP-filen direkt till repositoryts rot.
2. Öppna [Render Dashboard](https://dashboard.render.com/) och välj **New → Blueprint**.
3. Koppla GitHub-repositoryt. Render läser `render.yaml` och föreslår en kostnadsfri Python Web Service.
4. Ange **IKHP_ADMIN_PASSWORD** (ett unikt starkt testlösenord) och **IKHP_CLUB_PASSWORD** (ett annat testlösenord) när Render frågar efter miljövariablerna. Spara inte lösenorden i GitHub.
5. Klicka på **Apply / Deploy**. Vänta på lyckad driftsättning.
6. Öppna HTTPS-adressen som Render visar (ofta `https://ikhp-tavlingsportal-test.onrender.com` om namnet är ledigt). Den exakta adressen bestäms av Render.
7. Testa kalendern, **Visa anmälda**, anmälan och administratörens **Historik och anmälningar**.

## 2. Vad är förifyllt?
Två tydligt märkta DEMO-tävlingar för 2027 och tre påhittade deltagare. Alla anmälningar visas offentligt med namn, klass och grenar. Testa gärna med namn som `Testperson Ett` och e-post som `test@example.invalid`.

## 3. Viktiga begränsningar
- **Ingen riktig e-post skickas** i testmiljön, även om SMTP-variabler finns. Bekräftelsen visas i appen.
- **Ingen extern anmälan skickas**. Knappen är inaktiv.
- SQLite-databasen ligger på Render-instansens tillfälliga filsystem. **Data kan försvinna vid omstart, ny driftsättning eller annan återställning**. De inbyggda DEMO-uppgifterna skapas då igen.
- Administratörshistorik kräver inloggning och API:et svarar 403 utan administratörssession.
- Testmiljön har grundläggande skydd men är **inte godkänd för verkliga personuppgifter eller skarp drift**. Produktionsdrift kräver bland annat säkerhetsgranskning, CSRF-strategi, bättre sessions- och lösenordshantering, beständig databas, backup och GDPR-rutiner.
- Det finns ingen import från EasyRecord, Track and Field, Webathletics eller Friidrottsanmälan.
- Bankgiro är en platshållare och efteranmälningsbetalningar ska inte göras i testmiljön.
- Render kan ändra tillgängliga planer och Blueprint-beteende. Kontrollera plan och eventuell kostnad i Render innan du godkänner.

## 4. Köra lokalt
Python 3.10 eller senare, inga extra paket.

Windows PowerShell:
```powershell
$env:IKHP_ADMIN_PASSWORD="eget-starkt-testlösenord"
$env:IKHP_CLUB_PASSWORD="eget-annat-testlösenord"
python server.py
```
macOS/Linux:
```bash
export IKHP_ADMIN_PASSWORD='eget-starkt-testlösenord'
export IKHP_CLUB_PASSWORD='eget-annat-testlösenord'
python3 server.py
```
Öppna http://localhost:8080.

## 5. Förväntat testflöde
1. Kalendern visar två demotävlingar.
2. Visa anmälda visar påhittade deltagare.
3. Gör en anmälan med födelseår 2012 till F15 eller P15 i Junespelen 2027 och med klubbens testlösenord.
4. Appen bekräftar mottagandet, men skickar inget mejl.
5. Logga in under Administration, öppna Historik, markera en anmälan som officiellt registrerad (endast som test).
6. Kontrollera att Historik inte finns i den publika menyn och att admin-API kräver inloggning.

## 6. Filer
- `server.py`: Pythonserver, SQLite, testdata, adminsessioner och API.
- `index.html`: responsivt användargränssnitt.
- `render.yaml`: Render Blueprint.
- `.gitignore`: hindrar oavsiktlig incheckning av lokal databas.

## Redigera manuellt registrerade tävlingar
Under Administration → Tävlingar och publicering, välj **Redigera tävling**. Ändra namn, datum, länk, publicering, klasser, grenar och avgifter. Lägg till eller ta bort klasser och grenar och välj **Spara ändringar**. Endast manuella tävlingar (inklusive demodata) kan ändras. Redan gjorda anmälningar ändras inte retroaktivt.

## Uppdatering v3 – anmälda i tabell
Knappen **Visa anmälda** visar nu en tabell med en rad per anmälan och kolumnerna **Namn**, **Klass** och **Grenar**. Alla grenar för en anmälan står i samma cell. Tabellen kan scrollas i sidled på smala skärmar.

## Uppdatering v4 – klassval
Vid anmälan visas samtliga klasser som finns upplagda för tävlingen, även om klassens ålder eller kategori avviker från deltagarens. Efter att födelseår och kön angetts väljs automatiskt närmaste klass i motsvarande kategori (om sådan finns), märkt "föreslagen". Användaren kan välja en annan klass i listan. Servern kontrollerar att klassen finns i tävlingen men tillämpar inte längre ålders- eller könsspärrar. Administratören behöver därför kontrollera arrangörens regler vid officiell vidareanmälan.


## Uppdatering v5 – klassregler
- Föreslagen klass är den närmaste tillåtna åldersklassen **lika med eller över** deltagarens tävlingsålder. En 12-åring får F13/P13 om 12-årsklass saknas. Om ingen högre tillåten klass finns väljs närmaste yngre klass.
- Klasser med åldersgräns **upp till och med 35** är öppna för deltagare i samma könskategori oavsett ålder.
- Klasser **över 35** kräver att deltagaren uppnått klassens ålder under tävlingsåret.
- **KS** (kvinnor) och **MS** (män) är alltid öppna för alla åldrar inom respektive kategori.
- Endast tillåtna klasser visas i rullistan. Servern gör samma kontroll vid registrering.
- Ålder beräknas som tävlingsår minus födelseår.


## Version 6 – korrigerade klassregler
- Upp till 35 års tävlingsålder: endast närmaste tillgängliga åldersklass som är minst lika hög som deltagarens ålder, och högst 35, plus KS/MS. Exempel: 20 år → M22 och MS om M22 finns.
- Över 35 år: endast klasser med klassålder högst deltagarens tävlingsålder samt KS/MS. Exempel: 42 år → M40, M35 och MS om dessa finns, men aldrig M45.
- Både webbgränssnitt och server validerar samma regler.
