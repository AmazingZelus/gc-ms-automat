# CLAUDE.md – pravidla projektu GC-MS Automat

Tato pravidla platí pro každého agenta i člověka, který na projektu pracuje. Při konfliktu s obecnými zvyklostmi mají přednost.

## O projektu a uživatelce

- Přenosná aplikace pro Windows na zpracování dat GC-MS (později i další chromatografie, např. HPLC-FLD). Uživatelé jsou studenti a kolegové z chemie potravin, často bez zkušeností s programováním.
- Vlastnice projektu je chemička (PhD, chemie a technologie potravin) a neprogramuje. **Technická rozhodnutí děláš ty, ale vysvětli je česky a srozumitelně.** S ní komunikuj česky.
- **Kód je anglicky:** názvy proměnných, funkcí a souborů s kódem. **Texty v UI a uživatelská dokumentace jsou česky.**
- Po každém logickém úseku kódu napiš krátký anglický komentář, co ta část dělá (např. `# This loads the .cdf file`, `// This is the window where the chromatograms show`).

## Architektura (stručně)

```
spustit.bat                   start pro uživatele (jen ASCII, CRLF, bez bloků v závorkách)
app/main.py                   start serveru: volný port, token, prohlížeč, watchdog
app/gcms_automat/__init__.py  JEDINÉ místo s názvem a verzí (APP_NAME, __version__)
app/gcms_automat/server.py    Flask: UI + JSON API (/api/...), CSP, kontrola tokenu a Host
app/gcms_automat/lifecycle.py kdy se server ukončí (heartbeat, zavření karty, Ukončit)
app/gcms_automat/export.py    VŠECHNY exporty jdou přes write_csv_export() (hlavička s verzí)
app/gcms_automat/paths.py     složky; vše se zapisuje jen do složky aplikace
app/gcms_automat/static/      HTML/JS/CSS – vše lokálně, žádné CDN
tools/build_portable.py       sestavení ZIPu (embeddable Python + zamčené balíčky)
tools/smoke_test.ps1          test hotového ZIPu na Windows (spouští ho CI)
requirements/runtime.in       přímé závislosti → tools/make_lock.py → runtime.lock.txt (s hashi)
```

Proč takto: Flask + waitress + čisté HTML/JS je nejjednodušší spolehlivá varianta, která funguje úplně offline. Nic se nestahuje za běhu a není potřeba žádný build krok pro frontend. Grafy se později přidají přibalením `plotly.min.js` do `static/vendor/`.

## Pravidla (povinná)

1. **Úplně offline.** Žádné CDN, webové fonty, analytika, kontroly aktualizací ani jakékoli síťové požadavky za běhu. Každá JS/CSS knihovna se přibalí do `app/gcms_automat/static/vendor/` i s licencí. CSP hlavička v `server.py` musí zůstat `'self'`. Server poslouchá jen na `127.0.0.1`.
2. **Zapisuje se jen do složky aplikace** (`exporty/`, `logs/`, `runtime/`). Nic do `%APPDATA%`, registru ani domovské složky.
3. **Jen zavedené, citovatelné knihovny** (numpy, scipy, pandas, statsmodels, scikit-learn…). Žádné vlastní implementace statistiky ani standardních algoritmů (fitování, integrace, vyhlazování, PCA, regrese…). Novou knihovnu přidej do `requirements/runtime.in`, spusť `python tools/make_lock.py` a v commitu zdůvodni proč. Musí mít wheel pro Windows a Python 3.14.
4. **Verze v exportech.** Verze je definovaná jen v `app/gcms_automat/__init__.py`. Každý export (CSV, XLSX, PDF, obrázek…) musí obsahovat název aplikace, verzi a datum a čas zpracování s časovou zónou. CSV vždy přes `write_csv_export()`. Nový formát exportu dostane obdobnou hlavičku nebo metadata a test, který to ověří.
5. **Testy výpočtů na syntetických datech se známým výsledkem.** Každá výpočetní funkce má test v `tests/` na vygenerovaných datech, kde výsledek známe předem (např. Gaussův pík se známou plochou, přímka se známou směrnicí). Uveď toleranci a proč je taková. Testy nesmí potřebovat skutečná měřená data ani internet.
6. **Komentář se vzorcem a jednotkami u každého výpočtu.** Např. `# Resolution R = 2 (t2 - t1) / (w1 + w2); t in min, w = baseline peak width in min`. U převzaté metody uveď zdroj (dokumentace knihovny, norma nebo publikace). **Citace si nikdy nevymýšlej.** Pokud si zdrojem nejsi jistý, napiš `TODO: ověřit zdroj` a řekni to uživatelce.
7. **Žádné vymyšlené konstanty.** Každý parametr, který ovlivňuje výsledek (práh šumu, okno vyhlazování, tolerance RT…), je nastavitelný v UI. Má výchozí hodnotu, jednotku a krátké české vysvětlení, co dělá a jak ho zvolit. Výchozí hodnotu zdůvodni v komentáři (zdroj nebo úvaha). Použité hodnoty parametrů se zapisují do hlavičky exportu.
8. **Čitelnost před chytrostí.** Krátké funkce, popisné názvy, typové anotace. Kód budou číst lidé, kteří neprogramují denně.
9. **Spouštěcí skript** `spustit.bat`: jen ASCII, konce řádků CRLF (hlídá `.gitattributes`), žádné bloky `( … )`, cesty v uvozovkách. Musí fungovat i v cestách s mezerami, diakritikou, závorkami a na síťovém disku.
10. **Repozitář je veřejný.** Žádná data pacientů ani firem, neveřejná měření, hesla, tokeny ani interní dokumenty. Testovací data jen syntetická.

## Postup práce: autor → recenzent

1. **Autor** napíše kód, spustí `python -m pytest` a vše, co se dá ověřit lokálně (spuštění serveru, export, ideálně UI v headless prohlížeči).
2. Pak spustí **nového nezávislého agenta jako recenzenta** (ne fork, nesmí vidět vývoj). Předá mu zadání a tato pravidla. Recenzent zkontroluje minimálně:
   - offline (hledá `http`, CDN, externí odkazy a síťová volání),
   - dodržení pravidel 1–10,
   - správnost výpočtů a testů (známý výsledek, rozumné tolerance),
   - sestavení pro Windows a robustnost `spustit.bat`,
   - ukončení serveru a verzi v exportech,
   - čitelnost.

   Vrátí nálezy seřazené podle závažnosti (**kritické / důležité / drobnost**), každý s konkrétním scénářem selhání. Sám nic neopravuje.
3. Autor opraví kritické a důležité nálezy. U odmítnutých napíše proč.
4. Opakuje se to, dokud nezůstane nic kritického ani důležitého, **nejvýše 3 kola**. Co zůstane, se uvede ve shrnutí pro uživatelku.

## Vydání verze

1. Zvyš `__version__` v `app/gcms_automat/__init__.py` (MAJOR.MINOR.PATCH).
2. Commit a push do `main`. Počkej, až CI projde.
3. `git tag vX.Y.Z && git push origin vX.Y.Z`. CI ověří, že tag odpovídá verzi, sestaví a otestuje ZIP a vytvoří GitHub Release.

## Známá omezení ukončování (vyřešit, než aplikace začne držet data v paměti)

- Prohlížeč může neaktivní kartu „uvolnit“ a poslat přitom stejný signál jako při zavření (`pagehide`). Server se pak za 8 s ukončí, i když karta v liště zůstala. Teď to ničemu nevadí, ale s načtenými daty by se ztratila práce. Ověřit na skutečných prohlížečích ve Windows (Edge spící karty, Chrome Memory Saver, Firefox tab unloading) a případně přidat ukládání stavu nebo potvrzení.
- Při pádu prohlížeče nepřijde žádné rozloučení a server běží (s viditelným černým oknem) až 4 h. Je to záměrný kompromis, aby se aplikace neukončila uživateli, který pracuje v jiném programu.
- Dočasné soubory: do `runtime/tmp` se přesměrovává jen `tempfile` hlavního procesu. Podprocesy (např. scikit-learn s `n_jobs>1`, externí převodníky) dostanou systémový `%TEMP%`. Až se budou používat, předej jim `env` s `TEMP`/`TMP` = `runtime\tmp` (prohlížeči ne). Obsah `runtime/tmp` se zatím nemaže.
- Ukončení přes `os._exit` neřeší rozběhnuté požadavky. Až budou exporty velké, zapisuj nejdřív do dočasného souboru a pak ho přejmenuj, nebo před ukončením počkej na dokončení.

## Co jde ověřit jen na skutečném Windows

CI běží na Windows runneru, ale ten má předinstalované věci, které běžný počítač mít nemusí (např. Visual C++ runtime) a nemá SmartScreen ani interaktivní prohlížeč. Po větších změnách sestavení nebo spouštění proto požádej uživatelku o ruční test na čistém počítači.
