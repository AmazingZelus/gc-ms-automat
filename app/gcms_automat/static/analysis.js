// GC-MS analysis screen: settings, files, alkanes, result table, detail with plots.
// All numbers come from the local server (/api/...); this file only shows them.
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const api = window.App.api;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtArea = new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 });
  const fmt = (v, d) => (v === null || v === undefined ? "" : Number(v).toFixed(d));

  const state = {
    meta: [], params: {}, files: [], alkanes: [], table: null,
    sel: null, checked: new Set(), detail: null,
    view: { centre: null, half: 0.4 }, yzoom: { scale: 1, fit: false }, highlight: null, split: null, drag: null, geom: null,
  };

  function say(id, text, kind) {
    const el = $(id); el.textContent = text || "";
    el.classList.toggle("err", kind === "err"); el.classList.toggle("ok", kind === "ok");
  }

  // ================================================================ settings form
  // ---- This builds the settings form from the parameter descriptions ----
  function buildForm() {
    const form = $("params"); form.innerHTML = "";
    const groups = new Map();
    for (const p of state.meta) { if (!groups.has(p.group)) groups.set(p.group, []); groups.get(p.group).push(p); }
    // "Pokročilé" (advanced) always comes last, folded.
    const ordered = [...groups].sort((a, b) => (a[0] === "Pokročilé") - (b[0] === "Pokročilé"));
    for (const [group, items] of ordered) {
      const box = document.createElement(group === "Pokročilé" ? "details" : "fieldset");
      if (group === "Pokročilé") { box.className = "adv"; box.innerHTML = "<summary class='help'>Pokročilé</summary>"; }
      else box.innerHTML = `<legend>${esc(group)}</legend>`;
      for (const p of items) box.appendChild(fieldFor(p));
      form.appendChild(box);
    }
  }

  // ---- This creates one input for one parameter ----
  function fieldFor(p) {
    const id = "p-" + p.key;
    const wrap = document.createElement("div");
    if (p.kind === "bool") {
      wrap.className = "check";
      wrap.innerHTML = `<input id="${id}" type="checkbox"><label for="${id}">${esc(p.label)}</label><small>${esc(p.help)}</small>`;
      wrap.querySelector("input").addEventListener("change", (e) => changed(p, e.target.checked));
    } else if (p.kind === "choice") {
      // A choice from a fixed list (e.g. the baseline under the peaks).
      wrap.className = "field wide";
      wrap.innerHTML = `<label for="${id}">${esc(p.label)}</label><select id="${id}"></select><small>${esc(p.help)}</small>`;
      const sel = wrap.querySelector("select");
      for (const [value, label] of p.options) {
        const o = document.createElement("option"); o.value = value; o.textContent = label; sel.appendChild(o);
      }
      sel.addEventListener("change", () => changed(p, sel.value));
    } else if (p.kind === "ions") {
      // m/z list: typed into the box, applied only after Enter (the analyst confirms).
      wrap.className = "field wide";
      wrap.innerHTML = `<label for="${id}">${esc(p.label)} <span class="unit">${esc(p.unit)}</span></label>
        <input id="${id}" type="text" placeholder="např. 207 281 355, potvrď Enterem">
        <div class="chips" id="${id}-chips"></div><small>${esc(p.help)}</small>`;
      wrap.querySelector("input").addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const typed = e.target.value.split(/[\s,;]+/).filter(Boolean).map(Number);
        if (typed.some((m) => !Number.isFinite(m) || m <= 0)) { say("run-status", "Zadej jen kladná čísla m/z.", "err"); return; }
        e.target.value = "";
        changed(p, [...new Set([...(state.params[p.key] || []), ...typed.map(Math.round)])].sort((a, b) => a - b));
      });
    } else {
      wrap.className = "field";
      const unit = p.unit ? ` <span class="unit">[${esc(p.unit)}]</span>` : "";
      wrap.innerHTML = `<label for="${id}">${esc(p.label)}${unit}</label>
        <input id="${id}" type="number" ${p.step ? `step="${p.step}"` : ""} ${p.minimum !== null ? `min="${p.minimum}"` : ""}
        ${p.maximum !== null ? `max="${p.maximum}"` : ""}>${p.help ? `<small>${esc(p.help)}</small>` : ""}`;
      wrap.querySelector("input").addEventListener("change", (e) => {
        const v = parseFloat(e.target.value);
        if (Number.isFinite(v)) changed(p, v); else e.target.value = state.params[p.key];
      });
    }
    addHelpToggle(wrap);
    return wrap;
  }

  // ---- This hides a parameter's explanation behind a small "?" button ----
  function addHelpToggle(wrap) {
    const small = wrap.querySelector("small"), label = wrap.querySelector("label");
    if (!small || !label || !small.textContent.trim()) return;
    small.hidden = true;
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "help-toggle"; btn.textContent = "?";
    btn.title = "Vysvětlení"; btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      small.hidden = !small.hidden; btn.setAttribute("aria-expanded", String(!small.hidden));
    });
    label.appendChild(btn);   // inside the label, so the form layout stays the same
  }

  // ---- This fills the form with the current values ----
  function fillForm() {
    for (const p of state.meta) {
      const el = $("p-" + p.key); if (!el) continue;
      if (p.kind === "bool") el.checked = !!state.params[p.key];
      else if (p.kind === "ions") renderChips(p);
      else if (p.kind === "choice") el.value = state.params[p.key];
      else el.value = state.params[p.key];
    }
  }
  function renderChips(p) {
    const box = $("p-" + p.key + "-chips"); box.innerHTML = "";
    for (const m of state.params[p.key] || []) {
      const chip = document.createElement("span"); chip.className = "chip";
      chip.innerHTML = `${m}<button type="button" aria-label="Odebrat ${m}">×</button>`;
      chip.querySelector("button").addEventListener("click", () => changed(p, state.params[p.key].filter((x) => x !== m)));
      box.appendChild(chip);
    }
  }

  // ---- This shows the values the server really uses (invalid input keeps the old value) ----
  // stage "view": only view parameters are taken over (pipeline ones typed but not
  // yet computed must stay in the form until Vyhodnotit).
  function syncParams(r, stage) {
    if (r.params) {
      for (const p of state.meta) if (!stage || p.stage === stage) state.params[p.key] = r.params[p.key];
      fillForm();
    }
    if (r.rejected && r.rejected.length)
      say("run-status", "Neplatná hodnota, ponechána původní: " + r.rejected.join(", ") + ".", "err");
  }

  // ---- This reacts to a changed parameter: view ones apply at once, others need Vyhodnotit ----
  let viewTimer = null;
  function changed(p, value) {
    state.params[p.key] = value;
    if (p.kind === "ions") renderChips(p);
    if (p.stage === "view") {
      clearTimeout(viewTimer);
      viewTimer = setTimeout(applyView, 150);
    } else if (state.table) $("dirty").hidden = false;
  }
  async function applyView() {
    if (!state.table) return;
    try {
      const r = await api("/api/view", { params: state.params });
      syncParams(r, "view"); setTable(r.table);
    } catch (e) { say("run-status", e.message, "err"); }
  }
  $("reset").addEventListener("click", () => {
    for (const p of state.meta) state.params[p.key] = state.defaults[p.key];
    fillForm(); if (state.table) { $("dirty").hidden = false; applyView(); }
  });

  // ================================================================ files
  // ---- This uploads dropped or chosen .CDF files ----
  const drop = $("drop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));
  $("file-in").addEventListener("change", (e) => { upload(e.target.files); e.target.value = ""; });

  async function upload(list) {
    const files = [...list].filter((f) => /\.cdf$/i.test(f.name));
    if (!files.length) { say("load-status", "Vyber soubory .CDF.", "err"); return; }
    say("load-status", `Načítám ${files.length} souborů…`);
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    try {
      const r = await api("/api/files", form);
      setState(r);
      const parts = [];
      if (r.added.length) parts.push(`Načteno ${r.added.length} souborů.`);
      if (r.replaced.length) parts.push(`Nahrazeno souborem se stejným názvem: ${r.replaced.join(", ")}.`);
      if (r.errors.length) parts.push("Nepodařilo se načíst: " + r.errors.join("; "));
      say("load-status", parts.join(" "), r.errors.length || r.replaced.length ? "err" : "ok");
    } catch (e) { say("load-status", "Nahrání selhalo: " + e.message, "err"); }
  }

  // ---- This shows the list of loaded files with their role ----
  function renderFiles() {
    const box = $("files"); box.innerHTML = "";
    for (const f of state.files) {
      const row = document.createElement("div"); row.className = "file";
      row.innerHTML = `<span class="nm"></span><span class="meta">skupina ${esc(f.group)} · ${f.scans} skenů · do ${f.rt_end} min</span>
        <select aria-label="Role souboru"><option value="sample">Vzorek</option><option value="alk">Alkany</option><option value="off">Nepoužít</option></select>
        <button class="btn btn-link" type="button" aria-label="Odebrat soubor">Odebrat</button>`;
      row.querySelector(".nm").textContent = f.name;
      const sel = row.querySelector("select"); sel.value = f.role;
      sel.addEventListener("change", async () => setState(await api("/api/files/role", { name: f.name, role: sel.value })));
      row.querySelector("button").addEventListener("click", async () => setState(await api("/api/files/remove", { name: f.name })));
      box.appendChild(row);
    }
    $("run").disabled = !state.files.some((f) => f.role === "sample");
    $("alk-auto").disabled = !state.files.some((f) => f.role === "alk");
  }

  // ================================================================ alkanes
  // ---- This shows the editable alkane table ----
  function renderAlkanes() {
    const wrap = $("alk-wrap");
    if (!state.alkanes.length) { wrap.innerHTML = '<div class="empty">Zatím žádné alkany. Bez nich se RI nepočítá.</div>'; return; }
    const t = document.createElement("table"); t.className = "alk";
    t.innerHTML = "<thead><tr><th>C</th><th>RT [min]</th><th>Zdroj</th><th></th></tr></thead>";
    const body = document.createElement("tbody");
    state.alkanes.forEach((a, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><input type="number" step="1" min="1" aria-label="Počet uhlíků"></td>
        <td><input type="number" step="0.001" min="0" aria-label="Retenční čas [min]"></td><td class="mono"></td>
        <td><button class="btn btn-link" type="button">Smazat</button></td>`;
      const [c, rt] = tr.querySelectorAll("input");
      c.value = a.carbons; rt.value = Number(a.rt).toFixed(3); tr.children[2].textContent = a.source;
      c.addEventListener("change", () => { a.carbons = parseInt(c.value, 10); a.source = "ručně"; saveAlkanes(); });
      rt.addEventListener("change", () => { a.rt = parseFloat(rt.value); a.source = "ručně"; saveAlkanes(); });
      tr.querySelector("button").addEventListener("click", () => { state.alkanes.splice(i, 1); saveAlkanes(); });
      body.appendChild(tr);
    });
    t.appendChild(body); wrap.innerHTML = ""; wrap.appendChild(t);
  }
  async function saveAlkanes() {
    try { setState(await api("/api/alkanes", { alkanes: state.alkanes })); say("alk-status", ""); await refreshTable(); }
    catch (e) {
      // Refused (e.g. repeated carbon number): show the error and the alkanes really in use.
      say("alk-status", e.message, "err");
      setState(await api("/api/state"));
    }
  }
  $("alk-add").addEventListener("click", () => {
    const last = state.alkanes[state.alkanes.length - 1];
    state.alkanes.push({ carbons: last ? last.carbons + 1 : 8, rt: last ? +(last.rt + 1).toFixed(3) : 5, source: "ručně" });
    saveAlkanes();
  });
  $("alk-auto").addEventListener("click", async () => {
    try { const r = await api("/api/alkanes/auto", {}); setState(r); say("alk-status", r.message, "ok"); await refreshTable(); }
    catch (e) { say("alk-status", e.message, "err"); }
  });
  $("alk-import-toggle").addEventListener("click", () => { $("alk-import").hidden = !$("alk-import").hidden; });
  $("alk-import-ok").addEventListener("click", async () => {
    try {
      const r = await api("/api/alkanes/import", { text: $("alk-text").value });
      setState(r); say("alk-status", r.message, "ok"); $("alk-import").hidden = true; await refreshTable();
    } catch (e) { say("alk-status", e.message, "err"); }
  });

  // ================================================================ computation
  // ---- This is the Vyhodnotit button (asks first if manual edits would be lost) ----
  let armTimer = null;
  $("run").addEventListener("click", async () => {
    const btn = $("run");
    const edited = state.table ? state.table.rows.filter((r) => r.edits.length || r.note).length : 0;
    if (edited && !btn.dataset.armed) {
      btn.dataset.armed = "1"; btn.textContent = `Opravdu? Zahodí ruční úpravy (${edited} řádků)`;
      clearTimeout(armTimer);
      armTimer = setTimeout(() => { delete btn.dataset.armed; btn.textContent = "Vyhodnotit"; }, 6000);
      return;
    }
    delete btn.dataset.armed; clearTimeout(armTimer);
    btn.disabled = true; btn.textContent = "Počítám…"; say("run-status", "");
    try {
      const r = await api("/api/run", { params: state.params });
      setState(r); state.sel = null; state.checked.clear(); state.split = null; setSplitUi(); setTable(r.table);
      say("run-status", `Hotovo: ${r.table.n_visible} látek v tabulce.`, "ok");
      syncParams(r);
    } catch (e) { say("run-status", e.message, "err"); }
    finally { btn.textContent = "Vyhodnotit"; btn.disabled = !state.files.some((f) => f.role === "sample"); }
  });

  function setState(r) {
    if (r.files) { state.files = r.files; renderFiles(); }
    if (r.alkanes) { state.alkanes = r.alkanes; renderAlkanes(); }
    if (r.dirty !== undefined) $("dirty").hidden = !(r.dirty && r.has_result);
  }
  async function refreshTable() {
    if (!state.table) return;
    const r = await api("/api/table"); setTable(r.table);
  }

  // ================================================================ table
  function setTable(table) {
    state.table = table;
    $("res-empty").hidden = true; $("res-body").hidden = false;
    $("dirty").hidden = !table.dirty;
    renderSummary(); renderTable();
    if (state.sel !== null && table.rows.some((r) => r.uid === state.sel)) loadDetail(false);
    else { state.sel = null; $("detail").hidden = true; }
  }

  function renderSummary() {
    const t = state.table, s = t.stats;
    const hiddenCount = t.rows.filter((r) => r.hidden).length;
    const parts = [[t.n_visible, "látek v tabulce"], [t.names.length, "vzorků"], [s.peaks, "píků nalezeno"]];
    if (s.co2) parts.push([s.co2, "vyřazeno jako šum CO₂"]);
    if (s.filled) parts.push([s.filled, "buněk dointegrováno"]);
    if (hiddenCount) parts.push([hiddenCount, "skryto filtrem"]);
    if (!t.has_alkanes) parts.push(["–", "bez alkanů, RI se nepočítá"]);
    $("summary").innerHTML = parts.map(([n, txt]) => `<span class="stat"><b>${n}</b>${esc(txt)}</span>`).join("");
  }

  // ---- This draws the result table (column order as agreed) ----
  function renderTable() {
    const t = state.table, showHidden = $("show-hidden").checked;
    let html = `<thead><tr><th><span class="help">✓</span></th><th class="num">ID</th><th class="num">RT [min]</th><th class="num">RI</th>
      <th>Top ionty m/z (rel. %)</th><th class="num" title="Nejhorší shoda spektra některého vzorku s referenčním spektrem řádku (1 = stejné spektrum)">Shoda spekter</th><th class="num">n (z ${t.names.length})</th><th>Poznámka</th>`;
    html += t.names.map((n) => `<th class="num">${esc(n)}</th>`).join("") + "</tr></thead><tbody>";
    for (const r of t.rows) {
      if (r.hidden && !showHidden) continue;
      const cls = [r.uid === state.sel ? "sel" : "", r.poor && !r.hidden ? "poor" : "", r.hidden ? "hidden-row" : ""].join(" ");
      const pills = [];
      if (r.hidden) pills.push(`<span class="pill">${esc(r.hidden)}</span>`);
      r.auto_notes.forEach((n) => pills.push(`<span class="pill warn">${esc(n)}</span>`));
      if (r.edits.length) pills.push(`<span class="pill" title="${esc(r.edits.join("; "))}">upraveno</span>`);
      html += `<tr data-uid="${r.uid}" class="${cls}"><td><input type="checkbox" aria-label="Vybrat řádek ${esc(r.label)}"
        ${state.checked.has(r.uid) ? "checked" : ""} ${r.deleted ? "disabled" : ""}></td>
        <td class="num">${esc(r.label)}</td><td class="num">${fmt(r.rt, 3)}</td><td class="num">${r.ri ?? ""}</td>
        <td class="mono">${esc(r.ions)}</td><td class="num sim">${fmt(r.sim_min, 2)}</td><td class="num">${r.n}</td>
        <td>${pills.join("")}${esc(r.note)}</td>`;
      for (const n of t.names) {
        const c = r.cells[n];
        const kind = c.v === null ? "nd" : c.s === "fill" ? "fill" : c.s === "man" ? "man" : "";
        html += `<td class="num ${kind}" title="${esc(c.title)}">${c.v === null ? "ND" : fmtArea.format(c.v)}</td>`;
      }
      html += "</tr>";
    }
    $("results").innerHTML = html + "</tbody>";
    $("undo").disabled = !t.can_undo;
    updateSelection();
  }
  $("show-hidden").addEventListener("change", renderTable);

  // ---- This handles clicks in the table: checkbox = select for merge, row = detail ----
  $("results").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-uid]"); if (!tr) return;
    const uid = Number(tr.dataset.uid);
    if (e.target.matches("input[type=checkbox]")) {
      if (e.target.checked) state.checked.add(uid); else state.checked.delete(uid);
      updateSelection(); return;
    }
    state.sel = uid; state.view.centre = null; state.highlight = null; state.split = null; setSplitUi();
    state.yzoom = { scale: 1, fit: false };
    document.querySelectorAll("#results tr.sel").forEach((x) => x.classList.remove("sel"));
    tr.classList.add("sel"); say("r-msg", "");
    loadDetail(true);
  });
  function updateSelection() {
    const uids = [...state.checked].filter((u) => state.table.rows.some((r) => r.uid === u && !r.deleted));
    state.checked = new Set(uids);
    $("merge").disabled = uids.length < 2;
    const labels = state.table.rows.filter((r) => state.checked.has(r.uid)).map((r) => r.label);
    $("sel-info").textContent = uids.length ? `Vybráno: ${labels.join(", ")}` : "Zaškrtni řádky pro sloučení.";
  }

  // ================================================================ edits
  // ---- This sends one manual edit and shows the result ----
  async function edit(body) {
    try {
      const r = await api("/api/edit", body);
      if (r.focus !== undefined) state.sel = r.focus;
      state.split = null; setSplitUi();
      setTable(r.table); say("r-msg", r.message, "ok");
    } catch (e) { say("r-msg", e.message, "err"); }
  }
  $("merge").addEventListener("click", async () => {
    await edit({ action: "merge", uids: [...state.checked] }); state.checked.clear(); updateSelection();
  });
  $("undo").addEventListener("click", async () => {
    try { const r = await api("/api/undo", {}); setTable(r.table); say("r-msg", r.message, "ok"); }
    catch (e) { say("r-msg", e.message, "err"); }
  });
  // A highlighted sample = the window is changed only in that sample.
  const windowEdit = (t0, t1) => edit({ action: "window", uid: state.sel, t0, t1,
    samples: state.highlight ? [state.highlight] : null });
  $("w-apply").addEventListener("click", () => windowEdit(parseFloat($("w-start").value), parseFloat($("w-end").value)));
  $("r-fill").addEventListener("click", () => edit({ action: "fill", uid: state.sel }));
  $("r-delete").addEventListener("click", () => {
    const row = currentRow(); if (row) edit({ action: "delete", uid: row.uid, deleted: !row.deleted });
  });
  $("r-note").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); edit({ action: "note", uid: state.sel, note: e.target.value }); }
  });
  const currentRow = () => state.table && state.table.rows.find((r) => r.uid === state.sel);

  // ---- This is the split mode (choose the split time in the plot or the box) ----
  function setSplitUi() {
    $("s-controls").hidden = state.split === null; $("s-start").hidden = state.split !== null;
    if (state.split !== null) $("s-at").value = state.split.toFixed(3);
  }
  $("s-start").addEventListener("click", () => {
    if (!state.detail) return;
    const w = state.detail.window; state.split = (w[0] + w[1]) / 2; setSplitUi(); draw();
  });
  $("s-cancel").addEventListener("click", () => { state.split = null; setSplitUi(); draw(); });
  $("s-at").addEventListener("input", () => { const v = parseFloat($("s-at").value); if (Number.isFinite(v)) { state.split = v; draw(); } });
  $("s-ok").addEventListener("click", () => edit({ action: "split", uid: state.sel, at: parseFloat($("s-at").value) }));

  // ================================================================ detail
  // ---- This loads chromatograms and the reference spectrum of the selected row ----
  let detailRequest = 0;
  async function loadDetail(resetView) {
    const row = currentRow(); if (!row) return;
    if (resetView || state.view.centre === null) { state.view.centre = row.rt; state.view.half = 0.4; }
    const t0 = state.view.centre - state.view.half, t1 = state.view.centre + state.view.half;
    const ticket = ++detailRequest;
    try {
      const d = await api(`/api/detail?uid=${row.uid}&t0=${t0}&t1=${t1}`);
      if (ticket !== detailRequest) return;             // a newer request is on its way
      state.detail = d; state.detail.t0 = t0; state.detail.t1 = t1;
      showDetail(resetView);
    } catch (e) { say("r-msg", e.message, "err"); }
  }

  function showDetail(fresh) {
    const d = state.detail, r = d.row;
    $("detail").hidden = false;
    $("det-title").textContent = `Řádek ${r.label} · RT ${fmt(r.rt, 3)} min${r.ri !== null ? " · RI " + r.ri : ""} · n ${r.n}/${state.table.names.length}`;
    $("w-start").value = d.window[0].toFixed(3); $("w-end").value = d.window[1].toFixed(3);
    $("r-delete").textContent = r.deleted ? "Obnovit řádek" : "Smazat řádek (šum)";
    $("r-fill").disabled = !Object.values(r.cells).some((c) => c.v === null);
    if (fresh) $("r-note").value = r.note || "";
    $("spec-ref-title").textContent = `Referenční spektrum (nejvyšší pík řádku: ${r.ref_run})`;
    renderLegend(); draw();
    Plot.spectrum($("spec-ref"), d.spectrum);
    if (state.highlight) loadSampleSpectrum(state.highlight); else clearSampleSpectrum();
  }

  // ---- This is the collapsible list of samples (click = highlight + its spectrum) ----
  function renderLegend() {
    const t = state.table, row = state.detail.row, styles = Plot.sampleStyles(t.names, t.groups);
    $("legend-summary").textContent = `Vzorky (${t.names.length})` + (state.highlight ? ` · zvýrazněn: ${state.highlight}` : "");
    const list = $("legend-list"); list.innerHTML = "";
    t.names.forEach((n, i) => {
      const c = row.cells[n];
      const b = document.createElement("button"); b.type = "button";
      b.className = "legend-item" + (state.highlight === n ? " active" : "");
      b.innerHTML = `<i class="${styles[i].dash ? "dash" : ""}"></i><span></span>
        <span class="val">${c.v === null ? "ND" : fmtArea.format(c.v)}</span>`;
      b.children[0].style.borderColor = styles[i].color;   // set via JS: allowed by the security policy
      b.children[1].textContent = n;
      b.addEventListener("click", () => {
        state.highlight = state.highlight === n ? null : n;
        renderLegend(); draw();
        if (state.highlight) loadSampleSpectrum(n); else clearSampleSpectrum();
      });
      list.appendChild(b);
    });
  }
  async function loadSampleSpectrum(name) {
    try {
      const s = await api(`/api/spectrum?uid=${state.sel}&sample=${encodeURIComponent(name)}`);
      const i = state.table.names.indexOf(name), style = Plot.sampleStyles(state.table.names, state.table.groups)[i];
      $("spec-sel-title").textContent = `${name} (${s.status}) · shoda s referencí ${s.similarity.toFixed(2)}`;
      Plot.spectrum($("spec-sel"), s.spectrum, style.color);
    } catch (e) { $("spec-sel-title").textContent = name + ": " + e.message; Plot.spectrum($("spec-sel"), null); }
  }
  function clearSampleSpectrum() {
    $("spec-sel-title").textContent = "Vyber vzorek v seznamu „Vzorky“"; Plot.spectrum($("spec-sel"), null);
  }

  // ---- This draws the chromatogram plot from the loaded detail ----
  function draw() {
    const d = state.detail; if (!d) return;
    const styles = Plot.sampleStyles(state.table.names, state.table.groups);
    const traces = d.traces.map((tr, i) => Object.assign({ style: styles[i] }, tr));
    const own = state.drag && state.drag.win ? state.drag.win : d.window;
    state.geom = Plot.chromatogram($("chrom"), { t0: d.t0, t1: d.t1, mode: $("view-mode").value, traces,
      highlight: state.highlight, windows: d.windows, own, split: state.split,
      yScale: state.yzoom.scale, yFit: state.yzoom.fit ? own : null });
    $("yzoom-fit").classList.toggle("active", state.yzoom.fit);
  }
  $("view-mode").addEventListener("change", draw);
  window.addEventListener("resize", () => { if (state.detail) { draw(); Plot.spectrum($("spec-ref"), state.detail.spectrum); } });

  // ---- This is zoom and pan (buttons and mouse wheel) ----
  let zoomTimer = null;
  function zoom(factor, around) {
    const v = state.view;
    const centre = around ?? v.centre;
    const half = Math.min(10, Math.max(0.02, v.half * factor));
    v.centre = centre + (v.centre - centre) * (half / v.half);
    v.half = half;
    clearTimeout(zoomTimer); zoomTimer = setTimeout(() => loadDetail(false), 60);
  }
  $("zoom-in").addEventListener("click", () => zoom(1 / 1.6));
  $("zoom-out").addEventListener("click", () => zoom(1.6));
  $("pan-left").addEventListener("click", () => { state.view.centre -= state.view.half * 0.5; loadDetail(false); });
  $("pan-right").addEventListener("click", () => { state.view.centre += state.view.half * 0.5; loadDetail(false); });
  $("zoom-reset").addEventListener("click", () => { state.yzoom = { scale: 1, fit: false }; loadDetail(true); });

  // ---- This is the height zoom: only the y axis changes, the time range stays ----
  function yzoom(factor) {
    state.yzoom.scale = Math.min(1000, Math.max(1, state.yzoom.scale * factor));
    draw();
  }
  $("yzoom-in").addEventListener("click", () => yzoom(2));
  $("yzoom-out").addEventListener("click", () => yzoom(0.5));
  $("yzoom-fit").addEventListener("click", () => {
    state.yzoom = { scale: 1, fit: !state.yzoom.fit };
    draw();
  });

  const chrom = $("chrom");
  chrom.addEventListener("wheel", (e) => {
    if (!state.geom) return;
    e.preventDefault();
    if (e.shiftKey) yzoom((e.deltaY || e.deltaX) > 0 ? 1 / 1.4 : 1.4);   // Shift + wheel = height
    else zoom(e.deltaY > 0 ? 1.25 : 1 / 1.25, state.geom.tAt(localX(e)));
  }, { passive: false });

  // ---- This is dragging in the plot: move window edges, draw a new window, or set the split ----
  const localX = (e) => e.clientX - chrom.getBoundingClientRect().left;
  const nearEdge = (x) => {
    const w = state.detail.window;
    if (Math.abs(state.geom.X(w[0]) - x) < 7) return "start";
    if (Math.abs(state.geom.X(w[1]) - x) < 7) return "end";
    return null;
  };
  chrom.addEventListener("pointerdown", (e) => {
    if (!state.detail || !state.geom) return;
    chrom.setPointerCapture(e.pointerId);
    const x = localX(e), t = state.geom.tAt(x);
    if (state.split !== null) { state.drag = { mode: "split" }; state.split = t; setSplitUi(); draw(); return; }
    const edge = nearEdge(x), w = state.detail.window;
    state.drag = edge === "start" ? { mode: "start", other: w[1] } : edge === "end" ? { mode: "end", other: w[0] } : { mode: "new", anchor: t };
  });
  chrom.addEventListener("pointermove", (e) => {
    if (!state.detail || !state.geom) return;
    const x = localX(e), t = state.geom.tAt(x), d = state.drag;
    if (!d) { chrom.style.cursor = state.split !== null ? "col-resize" : nearEdge(x) ? "ew-resize" : "crosshair"; return; }
    if (d.mode === "split") { state.split = t; setSplitUi(); draw(); return; }
    d.win = d.mode === "start" ? [Math.min(t, d.other - 0.001), d.other]
      : d.mode === "end" ? [d.other, Math.max(t, d.other + 0.001)] : [Math.min(d.anchor, t), Math.max(d.anchor, t)];
    $("w-start").value = d.win[0].toFixed(3); $("w-end").value = d.win[1].toFixed(3);
    draw();
  });
  const endDrag = () => {
    const d = state.drag; state.drag = null;
    if (!d || d.mode === "split" || !d.win) { draw(); return; }
    if (d.win[1] - d.win[0] < 0.003) { draw(); return; }   // a click, not a drag
    windowEdit(d.win[0], d.win[1]);
  };
  chrom.addEventListener("pointerup", endDrag);
  chrom.addEventListener("pointercancel", () => { state.drag = null; draw(); });

  // ================================================================ start
  // ---- This loads the parameter descriptions and the current state ----
  async function start() {
    try {
      const meta = await api("/api/params-meta");
      const st = await api("/api/state");
      state.meta = meta.params;
      state.params = st.params;
      state.defaults = Object.assign({}, st.defaults || st.params);
      buildForm(); fillForm(); setState(st);
      if (st.has_result) await refreshTable();
    } catch (e) { setTimeout(start, 1000); }   // server not reachable yet: try again
  }
  // ---- This asks before the tab is closed while there is a result (work in memory) ----
  window.addEventListener("beforeunload", (e) => {
    // (not after Ukončit / when the app is gone: then there is nothing left to keep)
    if (state.table && !document.body.classList.contains("offline")) { e.preventDefault(); e.returnValue = ""; }
  });

  start();
})();
