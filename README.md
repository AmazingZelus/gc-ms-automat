# GC-MS Automat

Aplikace pro zpracování dat z GC-MS. Běží na vašem počítači, **nic se neinstaluje** a **funguje úplně bez internetu**. Ovládá se v prohlížeči, ale data nikam neodcházejí.

> **Stav:** verze 0.1 je zatím jen kostra aplikace. Umí jen zkušební export, zpracování dat přibude v dalších verzích.

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

- **Verze** programu je vidět nahoře vedle názvu.
- **Export test** uloží zkušební CSV soubor do složky **`exporty`** uvnitř složky aplikace. Tlačítko **Otevřít složku s exporty** ji otevře.
- **Formát CSV:**
  - **Excel (česky)** (výchozí): oddělovač `;` a desetinná čárka. Správně se otevře v české verzi Excelu.
  - **Mezinárodní**: oddělovač `,` a desetinná tečka. Pro Python, R nebo anglický Excel.
- Každý export začíná hlavičkou (řádky začínající `#`): název aplikace, verze, datum a čas zpracování a verze použitých knihoven. Ve výsledcích tak vždy dohledáte, čím a kdy vznikly.

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
