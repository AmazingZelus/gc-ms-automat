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
app/gcms_automat/export.py    CSV exporty přes write_csv_export() (hlavička s verzí)
app/gcms_automat/xlsx_export.py  export výsledků do Excelu: list „Info“ (verze, čas, soubory, alkany, VŠECHNY
                              parametry, metody integrace se std. anglickými názvy a citacemi, knihovny),
                              listy ploch (ND/0/prázdné/vlastní text), průměry paralelek, „Původ hodnot“
app/gcms_automat/paths.py     složky; vše se zapisuje jen do složky aplikace
app/gcms_automat/analysis/    VÝPOČTY (bez webového kódu): cdf.py čtení AIA, signal.py baseline/píky/integrace,
                              spectra.py spektra a shoda, align.py zarovnání, retention.py RI a alkany,
                              table.py tabulka + ruční úpravy (žádné překryvy oken!), params.py VŠECHNY parametry
app/gcms_automat/session.py   stav aplikace (soubory, alkany, parametry, výsledek) + JSON pro UI
app/gcms_automat/api_analysis.py  JSON API výpočtu (/api/files, /api/run, /api/edit, …)
app/gcms_automat/static/      HTML/JS/CSS – vše lokálně, žádné CDN (plot.js = vlastní kreslení na canvas)
tests/synthetic.py            syntetické běhy se známými píky (Gauss: plocha = H·S·σ·√(2π)·60)
tools/build_portable.py       sestavení ZIPu (embeddable Python + zamčené balíčky)
tools/smoke_test.ps1          test hotového ZIPu na Windows (spouští ho CI)
requirements/runtime.in       přímé závislosti → tools/make_lock.py → runtime.lock.txt (s hashi)
```

Proč takto: Flask + waitress + čisté HTML/JS je nejjednodušší spolehlivá varianta, která funguje úplně offline. Nic se nestahuje za běhu a není potřeba žádný build krok pro frontend. Grafy se později přidají přibalením `plotly.min.js` do `static/vendor/`.

## Pravidla (povinná)

1. **Úplně offline.** Žádné CDN, webové fonty, analytika, kontroly aktualizací ani jakékoli síťové požadavky za běhu. Každá JS/CSS knihovna se přibalí do `app/gcms_automat/static/vendor/` i s licencí. CSP hlavička v `server.py` musí zůstat `'self'`. Server poslouchá jen na `127.0.0.1`.
2. **Zapisuje se jen do složky aplikace** (`exporty/`, `logs/`, `runtime/`). Nic do `%APPDATA%`, registru ani domovské složky.
3. **Jen zavedené, citovatelné knihovny** (numpy, scipy, pandas, statsmodels, scikit-learn…). Žádné vlastní implementace statistiky ani standardních algoritmů (fitování, integrace, vyhlazování, PCA, regrese…). Novou knihovnu přidej do `requirements/runtime.in`, spusť `python tools/make_lock.py` a v commitu zdůvodni proč. Musí mít wheel pro Windows a Python 3.14.
4. **Verze v exportech.** Verze je definovaná jen v `app/gcms_automat/__init__.py`. Každý export (CSV, XLSX, PDF, obrázek…) musí obsahovat název aplikace, verzi a datum a čas zpracování s časovou zónou. CSV vždy přes `write_csv_export()`, XLSX přes `xlsx_export.build_workbook()` (list „Info“). Při nové metodě výpočtu doplň řádek do `methods_table()` (standardní anglický název + citace, jen ověřená). Nový formát exportu dostane obdobnou hlavičku nebo metadata a test, který to ověří.
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

## Poznámky k metodě (aktuální stav)

- **Baseline:** arPLS z knihovny pybaselines (Baek a kol. 2015, Analyst 140, 250–257), tuhost log₁₀ λ = 7 (parametr). Vede středem šumu, drží se pod ocasy píků i pod hustými shluky. Dřívější klouzavé minimum/průměr dávalo u reálných dat záporné plochy a u malých píků systematickou chybu. Nevracet se k němu.
- **Šum (pro S/N)** se odhaduje z NEvyhlazeného signálu (raw − baseline); z vyhlazeného vychází asi poloviční.
- **Okno píku** (jako klasický integrátor): od vrcholu na obě strany do PRVNÍHO z: signál < max(1 % výšky, 1 σ šumu); sklon < 5 % nejstrmějšího sklonu píku (pík na hrbolu skončí u své paty); údolí k sousednímu píku. Sousední okna se dotýkají v údolí, nikdy se nepřekrývají.
- **Plocha** (`cluster_areas`): dotýkající se okna tvoří shluk; pod shlukem přímka od začátku do konce, v údolích kolmice. Režim „auto“: konce přímky na společné baseline, pokud shluk nekončí vysoko na hrbolu (pak na signálu). Ve všech ostatních místech se plochy přepočítávají přes `Analysis.reintegrate()` po každé úpravě.
- Zvednutí baseline na hrbol v režimu „auto“ jen když okraj > 5× úroveň konce (parametr); běžné píky se tak měří přesně jako s kolmicemi (test `test_isolated_peaks_auto_baseline_has_no_extra_scatter`).
- Smazané řádky zůstávají v geometrii shluku: smazání „šumu“ nemění plochy sousedů.
- **Známý kompromis** (parametr „Konec okna při zploštění“, výchozí 5 %): chvostující píky přijdou o část ocasu (EMG τ/σ 1,5 / 3 / 5 → −1 / −2 / −3 %); s 0–1 % se ocas zachová, ale píky na hrbolech se nadhodnotí až 5×. Hlídá `test_tailing_peak_area_tradeoff_is_as_documented`.
- **Neřešeno (příští verze):** malý pík na ocasu velkého chvostujícího píku dostane ocas pod sebou, tj. asi 2× svou plochu (chybí „tangent/exponential skim“; `test_small_peak_after_a_tailing_peak_is_a_known_limitation`). Propady signálu pod baseline (výpadek detektoru) dělají falešné píky. Saturovaný pík s plochým vrcholem se může rozpadnout na 2–3 řádky (ručně sloučit). Vše je vidět v grafu.
- Práh výšky (% největšího píku) se počítá jen uvnitř vyhodnocovaného RT rozsahu.
- **Min. plocha** (`min_area`) se uplatní AŽ po integraci: řádky s největší plochou pod prahem se označí jako smazané (zůstanou v geometrii shluku, plochy sousedů se nemění; test `test_min_area_does_not_change_neighbour_area`). Nefiltrovat píky před zarovnáním.
- Smazané/skryté řádky se nepočítají do pravidla „žádné překryvy“ (`live_rows`): pozdější úprava souseda může zabrat jejich okno a pak je nejde obnovit. Zatím jen zdokumentováno.
- **Alkany automaticky:** M⁺ po odečtení izotopu ¹³C fragmentu na 14n+1. Alkany se slabým M⁺ se NEodhadují, uživatel je doplní.
- **Váhy shody spekter** (intenzita^0,5 × m/z^1) = „běžně používané“ váhy podle Stein & Scott 1994 (J. Am. Soc. Mass Spectrom. 5, 859–866, tab. 3; ověřeno z článku). Jejich optimum pro hledání v knihovně: intenzita^0,6 × m/z^3 (tab. 2). Výchozí zatím 0,5/1 (prahy shody byly voleny s nimi).
- **Shoda spekter v tabulce** = nejhorší shoda mezi vzorky, kde má řádek plochu (ND se nepočítá).
- **Průměry paralelek** (export): jen když je látka ve VŠECH paralelkách skupiny, jinak chybějící (pravidlo uživatelky). SD výběrová (n − 1).
- Testy obsahují i chvostující píky (EMG), shluky na driftující baseline, malé píky vedle velkých a náhodné sekvence úprav (fuzz test, že se okna nikdy nepřekryjí). Při změně metody tyhle testy nesmí povolit.

## Známá omezení ukončování (vyřešit, než aplikace začne držet data v paměti)

- Prohlížeč může neaktivní kartu „uvolnit“ a poslat přitom stejný signál jako při zavření (`pagehide`). Server se pak za 8 s ukončí, i když karta v liště zůstala. Teď to ničemu nevadí, ale s načtenými daty by se ztratila práce. Ověřit na skutečných prohlížečích ve Windows (Edge spící karty, Chrome Memory Saver, Firefox tab unloading) a případně přidat ukládání stavu nebo potvrzení.
- Při pádu prohlížeče nepřijde žádné rozloučení a server běží (s viditelným černým oknem) až 4 h. Je to záměrný kompromis, aby se aplikace neukončila uživateli, který pracuje v jiném programu.
- Dočasné soubory: do `runtime/tmp` se přesměrovává jen `tempfile` hlavního procesu. Podprocesy (např. scikit-learn s `n_jobs>1`, externí převodníky) dostanou systémový `%TEMP%`. Až se budou používat, předej jim `env` s `TEMP`/`TMP` = `runtime\tmp` (prohlížeči ne). Obsah `runtime/tmp` se zatím nemaže.
- Od v0.2 drží server výsledek v paměti: po zavření karty s výsledkem čeká 120 s (WORK_GRACE_S), aby obnovená/přenačtená karta výsledek znovu načetla; prohlížeč se před zavřením karty s výsledkem zeptá. Uložení projektu na disk zatím není.
- Ukončení přes `os._exit` neřeší rozběhnuté požadavky. Až budou exporty velké, zapisuj nejdřív do dočasného souboru a pak ho přejmenuj, nebo před ukončením počkej na dokončení.

## Co jde ověřit jen na skutečném Windows

CI běží na Windows runneru, ale ten má předinstalované věci, které běžný počítač mít nemusí (např. Visual C++ runtime) a nemá SmartScreen ani interaktivní prohlížeč. Po větších změnách sestavení nebo spouštění proto požádej uživatelku o ruční test na čistém počítači.
