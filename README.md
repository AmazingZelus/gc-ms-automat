# GC-MS Automat

Aplikace pro zpracování dat z GC-MS. Běží na vašem počítači, **nic se neinstaluje** a **funguje úplně bez internetu**. Ovládá se v prohlížeči, ale data nikam neodcházejí.

> **Stav (verze 0.2):** načtení CDF, zarovnání píků, integrace, RI a tabulka výsledků s ručními úpravami. Export do Excelu přijde ve verzi 0.3.

## Co potřebujete

- Windows 10 nebo 11 (64bit)
- libovolný prohlížeč (Edge, Chrome, Firefox)
- asi 400 MB volného místa na disku (stažený ZIP + rozbalená aplikace)

## 1. Stažení

1. Otevřete stránku **[Releases](https://github.com/AmazingZelus/gc-ms-automat/releases/latest)**.
2. V části *Assets* stáhněte soubor `GC-MS-Automat-vX.Y.Z-windows-x64.zip`.

## 2. Rozbalení

1. *(Doporučeno)* Klikněte na stažený ZIP pravým tlačítkem → **Vlastnosti** → dole zaškrtněte **Odblokovat** → **OK**. Windows se pak při spuštění nebude ptát (viz bod 4).
2. Klikněte na ZIP pravým tlačítkem → **Extrahovat vše…** → **Extrahovat**. Vznikne složka `GC-MS-Automat-vX.Y.Z-windows-x64` a v ní hned `spustit.bat`.
3. Rozbalit můžete kamkoli, kam smíte zapisovat (Plocha, Dokumenty, flash disk…). Nerozbalujte ale do `C:\Program Files`, tam aplikace nemůže ukládat výsledky.

**Tip:** Volte spíš krátkou cestu, ideálně třeba `C:\GCMS`. Windows má limit 260 znaků na délku cesty k souboru a cesta k cílové složce může mít nejvýše asi 100 znaků. Pozor hlavně na složky synchronizované přes OneDrive s dlouhým názvem (např. `C:\Users\jmeno\OneDrive - Dlouhý název univerzity\Dokumenty\…`), tam může rozbalení selhat.

**Aplikaci nespouštějte přímo z otevřeného ZIPu**, vždy ji nejdřív rozbalte.

## 3. Spuštění

V rozbalené složce dvakrát klikněte na **`spustit.bat`**.

- Otevře se černé okno (konzole) a za chvíli i aplikace v prohlížeči.
- **Černé okno nezavírejte**, dokud s aplikací pracujete. Zavře se samo.

## 4. Varování „Systém Windows ochránil váš počítač“

Při prvním spuštění se může objevit modré okno **„Systém Windows ochránil váš počítač“** (Windows SmartScreen). Objevuje se u programů stažených z internetu, které nejsou podepsané placeným certifikátem. Neznamená to, že je program škodlivý.

1. Klikněte na odkaz **Další informace**.
2. Objeví se tlačítko **Přesto spustit**, klikněte na něj.

Varování se většinou ukáže jen jednou. Pokud jste ZIP před rozbalením odblokovali (bod 2.1), neukáže se vůbec.

**Bez tlačítka „Přesto spustit“?** Na některých počítačích s Windows 11 je zapnuté **Inteligentní řízení aplikací** (Smart App Control). To nepodepsané programy blokuje úplně a tlačítko „Přesto spustit“ nenabídne. Pomůže odblokování ZIPu *před* rozbalením (bod 2.1): smažte rozbalenou složku, ZIP odblokujte a rozbalte znovu. Pokud ani to nepomůže, obraťte se na správce IT.

Pokud zdroji nevěříte, zdrojový kód je celý veřejně v tomto repozitáři a ZIP sestavuje automaticky GitHub (viz záložka *Actions*). U každé verze je uveden i kontrolní součet SHA-256.

## 5. Práce s aplikací

1. **Soubory:** přetáhni do okna `.CDF` soubory (z ChemStationu: *File → Export Data to AIA Format*), vzorky i alkanový standard najednou. Soubor s „alk“ v názvu dostane roli *Alkany*, ostatní *Vzorek*. Roli můžeš změnit.
   - **Paralelky** se poznají podle posledního písmene za podtržítkem: `vzorek_1_a` a `vzorek_1_b` patří do skupiny `vzorek_1`.
2. **Alkany:** najdou se samy v souborech alkanů. Zkontroluj je, případně je přepiš, nebo vlož tabulku (řádky `C10; 4,567`). Bez alkanů se RI nepočítá.
3. **Nastavení:** každý parametr má výchozí hodnotu a vysvětlení. Parametry výpočtu se projeví po kliknutí na **Vyhodnotit**. Parametry v části *Zobrazení tabulky* (skrytí podle základního iontu, malých píků, N největších, zvýraznění špatné shody) platí hned a nikdy nemění vypočtená čísla.
4. **Tabulka:** ID, RT, RI, top ionty, nejhorší shoda spekter (červeně podbarvené = špatná), n (v kolika vzorcích je plocha), poznámka a plochy ve vzorcích. Najetím na buňku uvidíš okno integrace, S/N a shodu spektra.
5. **Detail řádku** (klikni na řádek):
   - chromatogramy všech vzorků kolem píku; kolečko myši nebo tlačítka + − ← → mění rozsah,
   - seznam **Vzorky**: klik zvýrazní chromatogram vzorku a ukáže jeho spektrum vedle referenčního,
   - **ruční úpravy:** tažení okna integrace, *Rozdělit pík* (vzniknou řádky `5_1` a `5_2`), *Sloučit vybrané* (zaškrtávátka v tabulce), *Integrovat i v ND*, *Smazat řádek*, vlastní poznámka. Tlačítko **Zpět** vrací poslední úpravu.
   - Okna integrace různých řádků se v jednom vzorku nikdy nepřekrývají. Úpravu, která by překryv způsobila, aplikace odmítne a napíše proč.

**Plochy** jsou v jednotkách *counts × s* (TIC po odečtení baseline, lichoběžníkové pravidlo) a nejsou přímo totožné s plochami z ChemStationu. Jak se integruje (nastavení *Integrace*):

- Baseline celého chromatogramu: metoda arPLS (Baek a kol., 2015, Analyst 140, 250–257).
- Okno píku končí, kde signál klesne skoro na baseline, kde se zploští (pík na širokém hrbolu), nebo v údolí k sousednímu píku. Sousední píky dělí kolmice v údolí.
- Píky na širokém hrbolu se měří nad spojnicí svých okrajů, takže hrbol se jim nezapočítá. V grafu je ta baseline čárkovaně.
- **Pozor u silně chvostujících píků:** s výchozím nastavením mohou přijít o několik % ocasu. Pro takové látky sniž „Konec okna při zploštění“ (např. na 1 %) a zkontroluj okno v grafu.
- Saturovaný pík (plochý vrchol) se může rozpadnout na víc řádků: spoj je tlačítkem *Sloučit vybrané*.

**Výsledek je jen v paměti:** zavřením aplikace nebo novým *Vyhodnotit* se ruční úpravy ztratí (aplikace se předtím zeptá). Export do Excelu přijde ve verzi 0.3.

## 6. Ukončení

Aplikace se ukončí sama, když:

- kliknete na **Ukončit** (vpravo nahoře), nebo
- zavřete kartu či okno prohlížeče (asi do 10 sekund), nebo
- se k ní prohlížeč několik hodin nepřipojí (např. po pádu prohlížeče).

Ukončit ji můžete i zavřením černého okna.

## Řešení problémů

| Problém | Co dělat |
|---|---|
| Hláška „Nenalezen soubor python\python.exe“ | ZIP není rozbalený, nebo chybí část souborů. Rozbalte ho znovu (bod 2). |
| Prohlížeč se neotevřel | V černém okně je celá adresa (`http://127.0.0.1:…/?token=…`). Zkopírujte ji do prohlížeče. Funguje jen během tohoto spuštění. |
| „Aplikace neodpovídá“ | Aplikace se ukončila (zavřené černé okno, tlačítko Ukončit, nebo karta byla několik hodin uspaná prohlížečem). Spusťte znovu `spustit.bat`. Pokud jen probouzíte počítač, chvíli vyčkejte, karta se připojí sama. |
| „Tato karta patří k dřívějšímu spuštění“ | Prohlížeč obnovil starou kartu. Zavřete ji a použijte kartu, kterou otevřel `spustit.bat`. |
| Export hlásí „Soubor nelze uložit“ | Složka je jen pro čtení (např. `Program Files` nebo síťový disk). Přesuňte aplikaci do Dokumentů. |
| Antivir hlásí problém | Jde o nepodepsaný program. Obraťte se na správce IT, kód je veřejný. |
| Něco jiného | Pošlete autorce soubor `logs\gcms-automat.log` ze složky aplikace. |

## Pro vývojáře

Pravidla projektu jsou v [`CLAUDE.md`](CLAUDE.md). Stručně:

```text
python -m pip install -r requirements/dev.txt
python -m pytest              # testy
python app/main.py            # spuštění bez sestavení
python tools/build_portable.py  # sestavení ZIPu (stáhne přenosný Python)
```

Nová verze: změňte `__version__` v `app/gcms_automat/__init__.py`, commitněte a vytvořte tag `vX.Y.Z`. GitHub Actions pak ZIP sestaví, otestuje a přiloží k Releases.
