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
    kind: str = "float"      # float | int | bool | ions
    stage: str = "pipeline"  # pipeline | view
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None


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
    # Baseline: rolling-minimum window [min]. Must be several times wider than the
    # widest peak. 1.75 min = 301 scans at 0.35 s/scan (previous version).
    baseline_window_min: float = 1.75
    # Savitzky-Golay smoothing window [scans]; 5 points / 2nd order (previous version).
    smooth_points: int = 5

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
    # CO2 noise: base peak m/z 44 and fewer than 3 other ions above 10 %.
    co2_filter: bool = True

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
    # values of the previous version. TODO: ověřit zdroj (weighting of this type is
    # described by Stein & Scott 1994, J. Am. Soc. Mass Spectrom.; exact optimal
    # exponents to be checked against the paper).
    weight_intensity_power: float = 0.5
    weight_mz_power: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Return the values as a plain dict (for JSON and export headers)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisParams":
        """Build parameters from (possibly partial / string) user input; invalid -> default."""
        # This converts every known key to its type; unknown keys are ignored.
        params = cls()
        for info in PARAMETERS:
            if info.key not in data:
                continue
            try:
                value = _convert(info, data[info.key])
            except (TypeError, ValueError):
                continue
            if info.minimum is not None and isinstance(value, (int, float)) and value < info.minimum:
                continue
            if info.maximum is not None and isinstance(value, (int, float)) and value > info.maximum:
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
    ParamInfo("baseline_window_min", "Okno baseline", "min",
              "Šířka klouzavého minima pro baseline. Musí být několikrát širší než nejširší pík.",
              "Detekce píků", minimum=0.05, step=0.05),
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
    ParamInfo("weight_intensity_power", "Váha intenzity (exponent)", "",
              "Shoda = kosinus vektorů intenzita^a × (m/z)^b.", "Pokročilé", minimum=0, maximum=3, step=0.1),
    ParamInfo("weight_mz_power", "Váha m/z (exponent)", "", "", "Pokročilé", minimum=0, maximum=3, step=0.1),
]
