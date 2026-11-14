# LeadHarvest — B2B Lead Scraper (Google Maps → Excel)

Unealtă de linie de comandă care caută pe **Google Maps** afaceri dintr-o nișă și o localitate
(ex. *„clinici stomatologice Timișoara”*), le verifică website-ul, le **clasifică în
`HOT_LEAD` / `WARM_LEAD` / `COLD_LEAD`** și exportă totul într-un **fișier Excel formatat**, gata
de folosit pentru vânzări B2B (ex. oferte de creare / refacere website).

**Ce extrage pentru fiecare firmă:** nume, categorie, rating, număr de recenzii, adresă, telefon,
website, link Google Maps, plus — din verificarea site-ului — statusul HTTP, dacă are HTTPS și
adresele de email găsite pe pagina principală.

```
python main.py -q "clinici stomatologice Timisoara" -l 50
  → exports/clinici_stomatologice_timisoara_20261114_180812.xlsx
     (rânduri colorate: HOT roșu, WARM galben, COLD alb + foaie „Sumar”)
```

---

## Cuprins

1. [Cum funcționează](#1-cum-funcționează)
2. [Clasificarea lead-urilor (HOT / WARM / COLD)](#2-clasificarea-lead-urilor-hot--warm--cold)
3. [Ce îți trebuie](#3-ce-îți-trebuie)
4. [Instalare locală](#4-instalare-locală)
5. [Utilizare](#5-utilizare)
6. [Opțiuni](#6-opțiuni)
7. [Fișierul Excel](#7-fișierul-excel)
8. [Baza de date și duplicatele](#8-baza-de-date-și-duplicatele)
9. [Rulare în cloud (Render / UptimeRobot)](#9-rulare-în-cloud-render--uptimerobot)
10. [Probleme frecvente](#10-probleme-frecvente)
11. [Structura proiectului](#11-structura-proiectului)
12. [Utilizare responsabilă](#12-utilizare-responsabilă)

---

## 1. Cum funcționează

Un rulaj trece prin 4 faze, afișate cu bare de progres în terminal:

1. **Colectare** — deschide Google Maps într-un browser Chromium automat (Playwright), caută
   termenul și derulează lista de rezultate până găsește `--limit` firme **noi**
   (cele deja existente în `leads.db` sunt sărite).
2. **Detalii** — deschide pagina fiecărei firme și extrage datele. O firmă care eșuează e reîncercată
   o dată, apoi sărită; rularea nu se oprește.
3. **Verificare website + scor** — verifică în paralel (8 simultan) site-ul fiecărei firme: răspunde?
   are HTTPS? ce emailuri apar pe pagină? Apoi îi dă tag-ul HOT/WARM/COLD.
4. **Export** — salvează în `leads.db` și scrie fișierul `.xlsx` în `exports/`.

`Ctrl+C` în timpul rulării oprește colectarea, dar **salvează și exportă** ce s-a extras până atunci.

## 2. Clasificarea lead-urilor (HOT / WARM / COLD)

Logica e gândită pentru cine vinde servicii web: cu cât prezența online e mai slabă, cu atât
lead-ul e mai „fierbinte”.

| Tag | Condiție | Motiv afișat în Excel |
|---|---|---|
| `HOT_LEAD` | nu are website | `Fara website` |
| `HOT_LEAD` | site-ul nu răspunde sau nu dă HTTP 200 | `Website picat (nu raspunde)` / `Website picat (HTTP 404)` |
| `HOT_LEAD` | site-ul nu are HTTPS (sau certificat SSL invalid) | `Website fara HTTPS` |
| `WARM_LEAD` | site OK cu HTTPS, dar sub `--review-threshold` recenzii (implicit 20) | `Putine recenzii (7 < 20)` |
| `COLD_LEAD` | site OK, HTTPS, recenzii suficiente | `Website OK, prezenta online solida` |

Regulile se verifică în ordinea din tabel; prima care se potrivește decide tag-ul.
Le poți modifica în `enricher.py`, funcția `score_lead`.

## 3. Ce îți trebuie

- **Python 3.10+** — [python.org](https://www.python.org/downloads/). La instalarea pe Windows
  bifează *„Add Python to PATH”*.
- **Git** — [git-scm.com](https://git-scm.com/).
- ~300 MB liberi pentru browserul Chromium descărcat de Playwright.
- Conexiune la internet. **Nu** e nevoie de chei API, conturi sau variabile de mediu.

## 4. Instalare locală

> 💡 Recomandare: ține proiectul într-un folder al tău (ex. `C:\Users\<tu>\b2b-lead-scraper`),
> nu în `C:\Windows\System32` — acolo Windows poate cere drepturi de administrator și poate bloca
> scrierea fișierelor.

**Windows (PowerShell):**
```powershell
git clone https://github.com/tudorel-gps/b2b-lead-scraper.git
cd b2b-lead-scraper

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Dacă PowerShell refuză `Activate.ps1` (*„running scripts is disabled”*), rulează o singură dată:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Linux / macOS:**
```bash
git clone https://github.com/tudorel-gps/b2b-lead-scraper.git
cd b2b-lead-scraper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # pe Linux, eventual: playwright install --with-deps chromium
```

**Configurare:** nu există fișier de configurare și nici variabile de mediu — totul se dă din linia
de comandă (vezi [Opțiuni](#6-opțiuni)). `leads.db` și folderul `exports/` se creează automat la prima rulare.

La fiecare sesiune nouă de terminal, activează din nou mediul virtual (`.\.venv\Scripts\Activate.ps1`)
înainte de `python main.py`.

## 5. Utilizare

```powershell
# 50 de clinici stomatologice din Timișoara
python main.py --query "clinici stomatologice Timisoara" --limit 50

# Browser vizibil, ca să vezi ce face (util când ceva nu merge)
python main.py -q "service auto Cluj-Napoca" -l 10 --visible

# Fișier de ieșire ales de tine + prag WARM la 50 de recenzii
python main.py -q "saloane infrumusetare Iasi" -l 100 --review-threshold 50 -o exports/iasi.xlsx

# Exportă doar lead-urile găsite în rularea curentă
python main.py -q "avocati Brasov" -l 30 --only-new
```

La final, terminalul afișează un tabel cu lead-urile noi și un rezumat, de exemplu:
```
✔ 50 noi · 2 esuate · exportate 50 (18 HOT / 9 WARM / 23 COLD)
Excel: C:\...\exports\clinici_stomatologice_timisoara_20261114_180812.xlsx
```

**Sfaturi pentru căutări bune:** scrie căutarea cum ai scrie-o în Google Maps — nișă + oraș
(`"cabinete veterinare Oradea"`). Pentru volume mari, împarte pe cartiere sau orașe în loc de un
singur `--limit 500`: Google Maps afișează oricum un număr limitat de rezultate per căutare
(de obicei ~120).

## 6. Opțiuni

| Opțiune | Implicit | Descriere |
|---|---|---|
| `--query`, `-q` | **obligatoriu** | Nișă + localitate, ex. `"clinici stomatologice Timisoara"` |
| `--limit`, `-l` | `20` | Număr maxim de lead-uri **noi** (cele deja în baza de date nu se numără) |
| `--visible` | oprit | Pornește browserul vizibil (pentru depanare) |
| `--db` | `leads.db` | Calea bazei de date SQLite |
| `--output`, `-o` | `exports/<query>_<data_ora>.xlsx` | Fișierul Excel de ieșire |
| `--review-threshold` | `20` | Sub acest număr de recenzii, un site OK devine `WARM_LEAD` |
| `--timeout` | `5` | Timeout (secunde) la verificarea fiecărui website |
| `--only-new` | oprit | Exportă doar rularea curentă (implicit: **toate** lead-urile din bază pentru acel query) |
| `--rotate-every` | `15` | Browser context + User-Agent nou la fiecare N pagini |

`python main.py --help` afișează aceeași listă.

## 7. Fișierul Excel

**Foaia „Leads”** — un rând per firmă, sortat HOT → WARM → COLD, apoi după numărul de recenzii:
- coloane: Tag, Motiv, Nume, Categorie, Rating, Recenzii, Telefon, Email, Website, Status site,
  HTTPS, Adresa, Link Google Maps, Cautare, Data extragerii;
- rânduri colorate după tag (HOT roșu deschis, WARM galben, COLD alb);
- header înghețat și filtre pe fiecare coloană (poți filtra direct doar `HOT_LEAD`);
- link-uri clicabile spre site și spre Google Maps.

**Foaia „Sumar”** — data generării, total lead-uri, câte HOT / WARM / COLD, câte au email și câte nu au website.

## 8. Baza de date și duplicatele

Toate lead-urile se salvează în `leads.db` (SQLite). Fiecare firmă e identificată prin ID-ul ei
Google (`0x…:0x…` din link), deci:
- **nu apar duplicate** între rulări — la a doua rulare a aceleiași căutări primești firme noi;
- `--limit` numără doar firmele noi;
- fără `--only-new`, Excel-ul conține tot ce s-a strâns vreodată pentru acel query.

Pentru a o lua de la zero, șterge (sau redenumește) `leads.db`. Baza poate fi deschisă și cu
[DB Browser for SQLite](https://sqlitebrowser.org/).

> `leads.db` și `exports/` sunt în `.gitignore`: conțin telefoane și emailuri ale firmelor și
> **nu trebuie urcate pe GitHub**. Fă-ți backup separat dacă ai nevoie de ele.

## 9. Rulare în cloud (Render / UptimeRobot)

**Nu e cazul pentru acest proiect.** LeadHarvest e o unealtă pe care o pornești manual când ai
nevoie de lead-uri: rulează câteva minute, scrie un fișier Excel și se oprește. Nu e un serviciu
care trebuie să stea pornit non-stop, deci **nu are nevoie de Render și nici de UptimeRobot**
(acelea sunt folosite pentru botul [ad_sniper](https://github.com/tudorel-gps/ad_sniper)).

În plus, pe un server ar apărea probleme practice: Chromium consumă multă memorie (planul gratuit
Render are 512 MB), fișierele Excel s-ar pierde la fiecare restart, iar Google Maps blochează mult
mai des IP-urile de datacenter decât pe cele de acasă. Rularea locală e varianta recomandată.

## 10. Probleme frecvente

| Simptom | Cauză / soluție |
|---|---|
| `Executable doesn't exist ... chromium` | Lipsește browserul: `playwright install chromium` (cu `.venv` activat). |
| `ModuleNotFoundError: No module named 'playwright'` (sau `rich`, `httpx`...) | Mediul virtual nu e activat sau dependențele nu sunt instalate: activează `.venv`, apoi `pip install -r requirements.txt`. |
| `Nu am gasit rezultate noi pentru aceasta cautare.` | Toate rezultatele sunt deja în `leads.db`, sau căutarea nu are rezultate. Încearcă alt oraș/termen sau rulează cu `--visible` să vezi ce afișează Google. |
| Multe firme `esuate` | Google încetinește sau blochează temporar. Scade `--limit`, fă pauză câteva ore între rulări mari. |
| Câmpuri goale (nume, rating, telefon) peste tot | Google și-a schimbat structura paginii. Selectorii sunt în `scraper.py`: `h1.DUwDvf`, `button.DkEaL`, `div.F7nice`, `data-item-id="address"`, `"phone:tel:"`, `"authority"`. Deschide o firmă în Chrome → F12 și actualizează-i. |
| Se blochează la pagina de cookies Google | Butoanele de consimțământ sunt în `CONSENT_BUTTONS` din `scraper.py`; adaugă textul butonului din limba ta. |
| `PermissionError` la scrierea `leads.db` / Excel | Proiectul e într-un folder protejat (ex. `C:\Windows\System32`) sau fișierul Excel e deschis în Excel. Mută proiectul în folderul tău / închide fișierul. |
| Diacritice stricate în terminal | Rulează `chcp 65001` înainte sau folosește Windows Terminal. |

## 11. Structura proiectului

| Fișier | Rol |
|---|---|
| `main.py` | CLI (argparse), orchestrarea celor 4 faze, bare de progres `rich`, rezumatul final |
| `scraper.py` | Motorul Playwright: caută, derulează lista, extrage detaliile, consimțământ cookies, rotire User-Agent, reîncercări |
| `enricher.py` | Verificarea site-urilor cu `httpx` (status, HTTPS, emailuri), clasificarea HOT/WARM/COLD |
| `database.py` | SQLite (`leads.db`), modelul `Lead`, deduplicare după ID-ul Google |
| `exporter.py` | Excel `.xlsx` cu formatare, filtre, header înghețat, culori, foaia „Sumar” |
| `requirements.txt` | Dependențe cu versiuni fixate |

**Tehnologii:** Python, [Playwright](https://playwright.dev/python/) (Chromium automat),
[httpx](https://www.python-httpx.org/), [openpyxl](https://openpyxl.readthedocs.io/),
[rich](https://rich.readthedocs.io/), SQLite.

## 12. Utilizare responsabilă

- Extragerea automată din Google Maps contravine termenilor de utilizare Google; folosește volume
  mici și rezonabile, pe propria răspundere. Pentru volume mari, varianta oficială e
  [Google Places API](https://developers.google.com/maps/documentation/places/web-service).
- Telefoanele și emailurile, chiar dacă sunt publice, pot fi date personale (ex. un cabinet
  individual). Conform **GDPR**, ai nevoie de un temei legitim pentru a contacta firmele, trebuie
  să le spui de unde ai datele și să ștergi datele cui îți cere. Nu vinde și nu publica listele.
