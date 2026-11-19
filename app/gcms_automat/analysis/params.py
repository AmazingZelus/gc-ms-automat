"""All user-adjustable parameters of the GC-MS analysis, with defaults and help.

This is the single source for: default values, units, Czech labels/help shown in
the UI, and the parameter list written into exports. The UI form is generated
from PARAMETERS, so a new parameter only has to be added here.

Two kinds of parameters:
  * "pipeline" parameters change the computation -> the user must click Vyhodnotit;
  * "view" parameters only filter/limit what the table shows -> applied instantly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


@dataclass(frozen=True)
class ParamInfo:
    """Description of one parameter for the UI and for export headers."""

    key: str
    label: str
    unit: str
    help: str
    group: str
    kind: str = "float"      # float | int | bool | ions | choice
    stage: str = "pipeline"  # pipeline | view
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: tuple = ()      # for kind "choice": ((value, Czech label), ...)


@dataclass
class AnalysisParams:
    """Parameter values. Defaults are justified in the comments next to each one."""

    # ---- Peak detection ----
    # Evaluated retention window; 0-100 min covers every normal GC run.
    rt_min: float = 0.0
    rt_max: float = 100.0
    # Minimum peak height relative to the largest peak of the run [%].
    # 0.2 % taken over from the previous (HTML) version of the tool; empirical.
    min_height_pct: float = 0.2
    # Minimum signal-to-noise ratio. 10 is the usual limit of quantification
    # convention (S/N 10:1; ICH Q2 guideline), so every reported peak is quantifiable.
    min_snr: float = 10.0
    # Baseline stiffness of arPLS as log10(lambda). 7: synthetic tests (tailing peak,
    # crowded cluster, small isolated peak) give areas within 1 % for 6..8, and the
    # real test run (7790 scans) has no negative areas for 6..8.
    baseline_log_lambda: float = 7.0
    # Savitzky-Golay smoothing window [scans]; 5 points / 2nd order (previous version).
    smooth_points: int = 5
    # Integration window end: where the signal falls to this % of the peak height.
    # 1 % = 2.9 sigma of a Gaussian peak -> only 0.4 % of the area is left out.
    window_end_pct: float = 1.0
    # ... or where it disappears into the noise (below this many noise sigma),
    # whichever comes first. 1 sigma: below it the signal cannot be told from noise.
    window_end_noise_sigma: float = 1.0
    # ... or where the signal flattens (slope below this % of the peak's steepest slope).
    # 5 %: a Gaussian ends at ~3 sigma (as with 1 % height); peaks on broad humps end
    # at their own foot (tests: areas within 0.99-1.13). Trade-off: tails of strongly
    # tailing peaks are cut (EMG tau/sigma 1.5 / 3 / 5 -> -1 / -2 / -3 %); 1 % keeps
    # tails but counts humps (up to 5x too large).
    window_end_slope_pct: float = 5.0
    # "auto" baseline: lift the line end onto the signal only if the signal there is
    # above this multiple of the end level (= 5 % of the height or 5 noise sigma at the
    # defaults). 5: an ordinary peak ends at ~1 % and is never lifted (tests: no bias,
    # scatter as with drop lines), a peak on a hump ends far higher (tens of %).
    integration_lift_factor: float = 5.0
    # Baseline under the peaks: "auto" = common baseline unless the peak/cluster ends on
    # a hump; "drop" = always the common baseline; "chord" = always edge to edge.
    integration_baseline: str = "auto"
    # Spectrum background: scans averaged just outside the window on each side.
    # 3 scans (~1 s at 0.35 s/scan) is close to the peak but averages the noise (previous version).
    spectrum_background_scans: int = 3

    # ---- Alignment between runs ----
    # Max. retention time difference for "the same compound" [min] (previous version).
    rt_tolerance_min: float = 0.04
    # Min. spectral similarity (cosine, 0-1) for "the same compound" (previous version).
    min_similarity: float = 0.70

    # ---- Filling a missing replicate ----
    fill_replicates: bool = True
    # S/N 3 = usual limit of detection convention (S/N 3:1; ICH Q2 guideline).
    fill_min_snr: float = 3.0
    # Min. spectral similarity for a filled-in peak (previous version).
    fill_min_similarity: float = 0.60

    # ---- Noise filters (pipeline) ----
    # CO2 noise: base peak m/z 44 and fewer than `co2_min_other_ions` other ions above
    # `co2_ion_pct` % (rule of the previous version; a real compound with base ion 44
    # normally has several other significant ions).
    co2_filter: bool = True
    co2_ion_pct: float = 10.0
    co2_min_other_ions: int = 3

    # ---- Alkane auto-detection ----
    # Minimum molecular ion M+ (after subtracting the 13C isotope peak of the
    # [M-H]+ fragment) to accept a carbon number [% of base ion] (previous version).
    alkane_min_molecular_ion_pct: float = 0.3

    # ---- View filters (instant, never change the computed numbers) ----
    # Hide rows whose base peak (100 % ion) is one of these m/z. Empty = off.
    hide_base_ions: list = field(default_factory=list)
    # Hide rows detected in fewer than N runs AND with largest area below A. 0 = off.
    small_max_detections: int = 0
    small_max_area: float = 0.0
    # Show only the N rows with the largest maximum area. 0 = all rows.
    top_n: int = 0
    # Flag rows whose worst spectral similarity is below this value.
    # 0.85 is a starting point (clearly above the alignment minimum 0.70);
    # set it from experience with your data.
    poor_match_below: float = 0.85

    # ---- Advanced: spectral similarity weighting ----
    # Similarity = cosine of (intensity^a * (m/z)^b) vectors. a = 0.5, b = 1 are the
    # values of the previous version, NOT taken from a paper. TODO: ověřit zdroj -
    # weighting of this type is studied by Stein & Scott 1994 (J. Am. Soc. Mass
    # Spectrom. 5, 859), whose optimum is reportedly different (unverified).
    weight_intensity_power: float = 0.5
    weight_mz_power: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Return the values as a plain dict (for JSON and export headers)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any], base: "AnalysisParams | None" = None,
                  rejected: list[str] | None = None) -> "AnalysisParams":
        """Build parameters from (possibly partial / string) user input.

        An invalid value keeps the previous value (from `base`, else the default);
        its label is appended to `rejected` so the user can be told.
        """
        # This converts every known key to its type; unknown keys are ignored.
        params = cls(**base.to_dict()) if base is not None else cls()
        rejected = rejected if rejected is not None else []
        for info in PARAMETERS:
            if info.key not in data:
                continue
            try:
                value = _convert(info, data[info.key])
            except (TypeError, ValueError):
                rejected.append(info.label)
                continue
            number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if number and ((info.minimum is not None and value < info.minimum) or
                           (info.maximum is not None and value > info.maximum)):
                rejected.append(info.label)
                continue
            setattr(params, info.key, value)
        return params


def parse_ions(value: Any) -> list[int]:
    """Parse '207, 281 355' or [207, 281] into a sorted list of unique m/z values."""
    # This accepts commas, semicolons and spaces as separators.
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).replace(",", " ").replace(";", " ").split()
    ions = sorted({int(round(float(x))) for x in items})
    if any(m <= 0 or m > 2000 for m in ions):
        raise ValueError("m/z out of range")
    return ions


def _convert(info: ParamInfo, value: Any) -> Any:
    """Convert one raw value to the parameter's type."""
    if info.kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "ano", "on", "yes")
        return bool(value)
    if info.kind == "int":
        return int(round(float(value)))
    if info.kind == "ions":
        return parse_ions(value)
    if info.kind == "choice":
        if value not in [o[0] for o in info.options]:
            raise ValueError("unknown option")
        return value
    number = float(value)
    if number != number:  # NaN
        raise ValueError("NaN")
    return number


# This is the list the UI is built from (order = order on screen).
PARAMETERS: list[ParamInfo] = [
    ParamInfo("rt_min", "RT od", "min", "Začátek vyhodnocovaného úseku. Ocas rozpouštědla dává falešné píky.",
              "Detekce píků", minimum=0, step=0.1),
    ParamInfo("rt_max", "RT do", "min", "Konec vyhodnocovaného úseku. Konec běhu (bleed kolony) dává falešné píky.",
              "Detekce píků", minimum=0, step=0.1),
    ParamInfo("min_height_pct", "Min. výška píku", "% největšího",
              "Výška po odečtení baseline, vztažená k největšímu píku daného záznamu.",
              "Detekce píků", minimum=0, maximum=100, step=0.01),
    ParamInfo("min_snr", "Min. poměr signál/šum", "S/N",
              "10 odpovídá obvyklé mezi stanovitelnosti (S/N 10:1). Pík musí splnit obě podmínky.",
              "Detekce píků", minimum=0, step=1),
    ParamInfo("smooth_points", "Vyhlazení", "skenů",
              "Okno Savitzky–Golayova vyhlazení (liché číslo, 2. řád). 0 nebo 1 = bez vyhlazení.",
              "Detekce píků", kind="int", minimum=0, maximum=51, step=2),
    ParamInfo("rt_tolerance_min", "Okno RT ±", "min",
              "Jak moc se může lišit RT téže látky mezi záznamy.", "Zarovnání", minimum=0.001, step=0.005),
    ParamInfo("min_similarity", "Min. shoda spekter", "0–1",
              "Pod touto shodou se píky nepovažují za stejnou látku.", "Zarovnání",
              minimum=0, maximum=1, step=0.05),
    ParamInfo("fill_replicates", "Dointegrovat chybějící paralelku", "",
              "Když je pík jen v jedné paralelce (např. _A), zkusí se integrovat i v druhé (_B) "
              "ve stejném okně. Číslo se zapíše jen tam, kde v okně opravdu je pík.",
              "Paralelky", kind="bool"),
    ParamInfo("fill_min_snr", "Dointegrace: min. S/N", "S/N",
              "3 odpovídá obvyklé mezi detekce (S/N 3:1).", "Paralelky", minimum=0, step=0.5),
    ParamInfo("fill_min_similarity", "Dointegrace: min. shoda spektra", "0–1", "", "Paralelky",
              minimum=0, maximum=1, step=0.05),
    ParamInfo("co2_filter", "Vyřadit šum CO₂", "",
              "Spektrum se základním iontem m/z 44 a méně než 3 dalšími ionty nad 10 %.",
              "Filtry šumu", kind="bool"),
    ParamInfo("hide_base_ions", "Skrýt píky se základním iontem", "m/z",
              "Napiš m/z (např. 207 281 355) a potvrď Enterem. Skryjí se řádky, jejichž "
              "nejintenzivnější iont je jedno z čísel. Data se nemažou, skryté řádky ukáže „Ukázat skryté“.",
              "Zobrazení tabulky", kind="ions", stage="view"),
    ParamInfo("small_max_detections", "Skrýt malé píky: nalezeno v méně než", "záznamech",
              "Spolu s plochou níže: skryje řádek, jen když platí obojí. 0 = vypnuto.",
              "Zobrazení tabulky", kind="int", stage="view", minimum=0, step=1),
    ParamInfo("small_max_area", "… a největší plocha pod", "",
              "Velký pík i v jediném vzorku zůstane. 0 = vypnuto.",
              "Zobrazení tabulky", stage="view", minimum=0, step=1000),
    ParamInfo("top_n", "Ukázat jen N největších", "řádků",
              "Podle největší plochy v řádku. 0 = všechny.", "Zobrazení tabulky",
              kind="int", stage="view", minimum=0, step=10),
    ParamInfo("poor_match_below", "Zvýraznit shodu spekter pod", "0–1",
              "Řádky, kde je nejhorší shoda spektra vůči referenci nižší, se podbarví červeně. "
              "0,85 je výchozí odhad, uprav podle zkušenosti.", "Zobrazení tabulky",
              stage="view", minimum=0, maximum=1, step=0.05),
    ParamInfo("baseline_log_lambda", "Tuhost baseline (log₁₀ λ)", "",
              "Baseline metodou arPLS (Baek a kol., 2015). Vyšší číslo = tužší, rovnější baseline. "
              "Obvykle 6–8. Na syntetických datech se plochy v tomto rozsahu mění o méně než 1 %; na reálných "
              "datech s hrboly se mohou plochy jednotlivých píků měnit víc, zkontroluj je v grafu.",
              "Pokročilé", minimum=3, maximum=11, step=0.5),
    ParamInfo("window_end_pct", "Konec okna píku", "% výšky",
              "Okno končí, kde signál klesne na toto % výšky píku nad baseline (1 % u Gaussova píku vynechá 0,4 % plochy), "
              "nebo v údolí k sousednímu píku.",
              "Integrace", minimum=0.1, maximum=50, step=0.5),
    ParamInfo("window_end_noise_sigma", "Konec okna v šumu", "× šum (σ)",
              "… nebo kde signál zapadne do šumu (pod tento násobek σ šumu), podle toho, co nastane dřív.",
              "Integrace", minimum=0, maximum=10, step=0.5),
    ParamInfo("window_end_slope_pct", "Konec okna při zploštění", "% max. sklonu",
              "Okno skončí, když sklon signálu klesne pod toto % nejstrmějšího sklonu píku. 5 % = pík na "
              "širokém hrbolu skončí u své paty. Nižší hodnota zachová delší ocasy chvostujících píků, "
              "ale může započítat hrbol pod píkem. 0 = vypnuto.", "Integrace", minimum=0, maximum=50, step=1),
    ParamInfo("integration_baseline", "Baseline pod píkem", "",
              "Nad čím se měří plocha píku. Automaticky: nad společnou baseline celého chromatogramu, ale když "
              "pík (nebo skupina dotýkajících se píků) končí vysoko na hrbolu, měří se nad spojnicí okrajů okna "
              "(hrbol se nezapočítá). Společná baseline: vždy nad ní (hrbol se započítá do píků). Spojnice "
              "okrajů: vždy nad přímkou mezi začátkem a koncem okna. Sousední dotýkající se píky se ve všech "
              "režimech dělí svislou čarou v údolí mezi nimi.",
              "Integrace", kind="choice",
              options=(("auto", "automaticky"), ("drop", "společná baseline (hrbol se započítá)"),
                       ("chord", "spojnice okrajů okna"))),
    ParamInfo("integration_lift_factor", "Hrbol pod píkem: práh", "× úroveň konce",
              "Režim „automaticky“ změří pík nad spojnicí okrajů jen tehdy, když okraj okna leží výš než "
              "tento násobek úrovně konce okna (výchozí 5 = 5 % výšky píku). Jinak měří od baseline.",
              "Integrace", minimum=1, maximum=100, step=1),
    ParamInfo("spectrum_background_scans", "Pozadí spektra", "skenů",
              "Kolik skenů těsně před a za oknem se průměruje jako pozadí odečtené od spektra.",
              "Pokročilé", kind="int", minimum=0, maximum=50, step=1),
    ParamInfo("co2_ion_pct", "CO₂: práh ostatních iontů", "%", "", "Pokročilé", minimum=0, maximum=100, step=1),
    ParamInfo("co2_min_other_ions", "CO₂: min. počet ostatních iontů", "",
              "Spektrum se základním iontem 44 je šum CO₂, pokud má méně ostatních iontů nad prahem.",
              "Pokročilé", kind="int", minimum=0, maximum=50, step=1),
    ParamInfo("alkane_min_molecular_ion_pct", "Alkany: min. molekulový iont", "%",
              "Pro automatické určení počtu uhlíků (po odečtení izotopu ¹³C fragmentu [M−H]⁺).",
              "Pokročilé", minimum=0, maximum=100, step=0.1),
    ParamInfo("weight_intensity_power", "Váha intenzity (exponent)", "",
              "Shoda = kosinus vektorů intenzita^a × (m/z)^b. Výchozí a = 0,5, b = 1 převzaty z předchozí "
              "verze nástroje (zdroj neověřen).", "Pokročilé", minimum=0, maximum=3, step=0.1),
    ParamInfo("weight_mz_power", "Váha m/z (exponent)", "", "", "Pokročilé", minimum=0, maximum=3, step=0.1),
]
