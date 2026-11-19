// Drawing of chromatograms and mass spectra on <canvas>. No external libraries.
"use strict";

const Plot = (() => {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // ---- This sizes a canvas for sharp lines on high-DPI screens ----
  function prepare(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.font = "11px " + css("--mono");
    return { g, w, h };
  }

  // ---- This picks "nice" axis tick values (1, 2, 5 x 10^n steps) ----
  function ticks(lo, hi, count) {
    const span = hi - lo;
    if (!(span > 0)) return [lo];
    const raw = span / count, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 5, 10].map((k) => k * mag).find((s) => span / s <= count) || 10 * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
    return out;
  }
  const shortNumber = (v) => (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "M" : Math.abs(v) >= 1e3 ? Math.round(v / 1e3) + "k" : String(Math.round(v)));

  // ---- This is the colour of each sample: one hue per replicate group, dashed 2nd replicate ----
  function sampleStyles(names, groups) {
    const unique = [...new Set(groups)];
    const hues = [215, 25, 150, 285, 45, 190, 330, 95, 0, 255, 120, 60];
    return names.map((n, i) => {
      const g = unique.indexOf(groups[i]);
      const nth = groups.slice(0, i).filter((x) => x === groups[i]).length;
      const light = 38 + (Math.floor(g / hues.length) % 3) * 12;
      return { color: `hsl(${hues[g % hues.length]} 62% ${light}%)`, dash: nth % 2 === 1 };
    });
  }

  // ---- This draws the chromatograms with integration windows ----
  // m: {t0, t1, mode, traces[{name, rt, raw, baseline, corr, style}], highlight,
  //     windows[{label, sample, t0, t1, own}], own:[a, b], split:t|null}
  function chromatogram(canvas, m) {
    const { g, w, h } = prepare(canvas);
    const lanes = Math.min(m.traces.length, 40);
    const pad = { l: 54, r: 12, t: 20, b: 30 + lanes * 2 };
    const X = (t) => pad.l + (t - m.t0) / (m.t1 - m.t0) * (w - pad.l - pad.r);

    // This finds the y range of the visible data.
    let lo = Infinity, hi = -Infinity;
    for (const tr of m.traces) {
      const ys = m.mode === "raw" ? tr.raw : tr.corr;
      for (let i = 0; i < tr.rt.length; i++) {
        if (tr.rt[i] < m.t0 || tr.rt[i] > m.t1) continue;
        hi = Math.max(hi, ys[i]); lo = Math.min(lo, ys[i]);
        if (m.mode === "raw") lo = Math.min(lo, tr.baseline[i]);
      }
    }
    if (!isFinite(hi)) { lo = 0; hi = 1; }
    if (m.mode !== "raw") lo = Math.min(0, lo);
    const span = (hi - lo) || 1; hi += span * 0.08; lo -= span * 0.02;
    const Y = (v) => h - pad.b - (v - lo) / (hi - lo) * (h - pad.t - pad.b);

    // This shades the windows of the other rows (one band per row, with its ID).
    const bands = new Map();
    for (const win of m.windows) {
      if (win.own) continue;
      const b = bands.get(win.label) || { t0: Infinity, t1: -Infinity };
      b.t0 = Math.min(b.t0, win.t0); b.t1 = Math.max(b.t1, win.t1); bands.set(win.label, b);
    }
    g.textAlign = "center";
    for (const [label, b] of bands) {
      const a = Math.max(b.t0, m.t0), z = Math.min(b.t1, m.t1);
      if (z <= a) continue;
      g.fillStyle = css("--neighbour"); g.fillRect(X(a), pad.t, X(z) - X(a), h - pad.t - pad.b);
      g.fillStyle = css("--warn"); g.fillText(label, (X(a) + X(z)) / 2, pad.t - 6);
    }

    // This shades the selected row's window.
    if (m.own) {
      g.fillStyle = "rgba(31, 95, 168, 0.10)";
      g.fillRect(X(m.own[0]), pad.t, X(m.own[1]) - X(m.own[0]), h - pad.t - pad.b);
      g.strokeStyle = css("--primary"); g.lineWidth = 2;
      for (const t of m.own) { g.beginPath(); g.moveTo(X(t), pad.t); g.lineTo(X(t), h - pad.b); g.stroke(); }
    }

    // This draws the axes and grid.
    g.lineWidth = 1; g.strokeStyle = css("--border"); g.fillStyle = css("--muted");
    for (const v of ticks(lo, hi, 4)) {
      g.beginPath(); g.moveTo(pad.l, Y(v)); g.lineTo(w - pad.r, Y(v)); g.stroke();
      g.textAlign = "right"; g.fillText(shortNumber(v), pad.l - 6, Y(v) + 4);
    }
    const span_t = m.t1 - m.t0;
    for (const v of ticks(m.t0, m.t1, 7)) {
      if (X(v) > w - pad.r - 60) continue;
      g.textAlign = "center"; g.fillText(v.toFixed(span_t < 1 ? 2 : 1), X(v), h - pad.b + 15);
    }
    g.textAlign = "right"; g.fillText("RT [min]", w - pad.r, h - pad.b + 15);

    // This draws the traces (the highlighted one on top, the others faded).
    const order = m.traces.map((_, i) => i).sort((a, b) => (m.traces[a].name === m.highlight) - (m.traces[b].name === m.highlight));
    g.save(); g.beginPath(); g.rect(pad.l, pad.t, w - pad.l - pad.r, h - pad.t - pad.b); g.clip();
    for (const i of order) {
      const tr = m.traces[i], ys = m.mode === "raw" ? tr.raw : tr.corr;
      const strong = !m.highlight || tr.name === m.highlight;
      g.globalAlpha = strong ? 1 : 0.18;
      g.strokeStyle = tr.style.color; g.lineWidth = tr.name === m.highlight ? 2.4 : 1.3;
      g.setLineDash(tr.style.dash ? [5, 3] : []);
      g.beginPath();
      tr.rt.forEach((t, k) => (k ? g.lineTo(X(t), Y(ys[k])) : g.moveTo(X(t), Y(ys[k]))));
      g.stroke();
      if (m.mode === "raw" && strong) {
        g.setLineDash([1, 3]); g.lineWidth = 1; g.beginPath();
        tr.rt.forEach((t, k) => (k ? g.lineTo(X(t), Y(tr.baseline[k])) : g.moveTo(X(t), Y(tr.baseline[k]))));
        g.stroke();
      }
    }
    // This draws the integration baseline of the selected row (dashed, per sample).
    if (m.mode !== "raw") {
      g.setLineDash([4, 3]); g.lineWidth = 1.5;
      for (const win of m.windows) {
        if (!win.own) continue;
        const tr = m.traces.find((t) => t.name === win.sample);
        if (!tr || (m.highlight && tr.name !== m.highlight)) continue;
        g.strokeStyle = tr.style.color;
        g.beginPath(); g.moveTo(X(win.t0), Y(win.base0)); g.lineTo(X(win.t1), Y(win.base1)); g.stroke();
      }
    }
    g.restore(); g.globalAlpha = 1; g.setLineDash([]);

    // This draws one thin lane per sample under the axis: its windows in this view.
    const laneY = (k) => h - lanes * 2 - 4 + k * 2;
    m.traces.slice(0, lanes).forEach((tr, k) => {
      for (const win of m.windows) {
        if (win.sample !== tr.name) continue;
        const a = Math.max(win.t0, m.t0), z = Math.min(win.t1, m.t1);
        if (z <= a) continue;
        g.strokeStyle = win.own ? tr.style.color : css("--warn");
        g.globalAlpha = win.own ? 1 : 0.5; g.lineWidth = 1.6;
        g.beginPath(); g.moveTo(X(a), laneY(k)); g.lineTo(X(z), laneY(k)); g.stroke();
      }
    });
    g.globalAlpha = 1;

    // This draws the split position (in split mode).
    if (m.split !== null && m.split !== undefined) {
      g.strokeStyle = css("--warn"); g.lineWidth = 2; g.setLineDash([6, 4]);
      g.beginPath(); g.moveTo(X(m.split), pad.t); g.lineTo(X(m.split), h - pad.b); g.stroke(); g.setLineDash([]);
      g.fillStyle = css("--warn"); g.textAlign = "center"; g.fillText("dělení " + m.split.toFixed(3), X(m.split), pad.t + 12);
    }
    return { pad, w, h, tAt: (x) => m.t0 + (x - pad.l) / (w - pad.l - pad.r) * (m.t1 - m.t0), X };
  }

  // ---- This draws a mass spectrum as a bar plot with m/z labels ----
  function spectrum(canvas, spec, color) {
    const { g, w, h } = prepare(canvas);
    if (!spec || !spec.mz.length) {
      g.fillStyle = css("--muted"); g.textAlign = "center"; g.fillText("—", w / 2, h / 2); return;
    }
    const pad = { l: 38, r: 10, t: 14, b: 26 };
    let lo = Math.min(...spec.mz.filter((m, i) => spec.i[i] >= 1));
    let hi = Math.max(...spec.mz.filter((m, i) => spec.i[i] >= 1));
    lo = Math.max(0, Math.floor((lo - 5) / 10) * 10); hi = Math.ceil((hi + 10) / 10) * 10;
    const X = (m) => pad.l + (m - lo) / (hi - lo) * (w - pad.l - pad.r);
    const Y = (v) => h - pad.b - v / 100 * (h - pad.t - pad.b);
    g.strokeStyle = css("--border"); g.fillStyle = css("--muted"); g.lineWidth = 1;
    for (const v of [0, 25, 50, 75, 100]) {
      g.beginPath(); g.moveTo(pad.l, Y(v)); g.lineTo(w - pad.r, Y(v)); g.stroke();
      g.textAlign = "right"; g.fillText(v + "%", pad.l - 4, Y(v) + 4);
    }
    for (const v of ticks(lo, hi, 6)) { g.textAlign = "center"; g.fillText(v, X(v), h - pad.b + 15); }
    g.strokeStyle = color || css("--primary"); g.lineWidth = 2;
    spec.mz.forEach((m, k) => { if (m < lo || m > hi) return; g.beginPath(); g.moveTo(X(m), Y(0)); g.lineTo(X(m), Y(spec.i[k])); g.stroke(); });
    // This labels the strongest ions (without overlapping labels).
    const order = spec.mz.map((_, k) => k).sort((a, b) => spec.i[b] - spec.i[a]).slice(0, 8);
    const placed = [];
    g.fillStyle = css("--text"); g.textAlign = "center";
    for (const k of order) {
      if (spec.mz[k] < lo || spec.mz[k] > hi) continue;   // ion outside the shown range
      const x = X(spec.mz[k]);
      if (placed.some((p) => Math.abs(p - x) < 22)) continue;
      placed.push(x); g.fillText(spec.mz[k], x, Math.max(Y(spec.i[k]) - 4, 11));
    }
  }

  return { chromatogram, spectrum, sampleStyles };
})();
