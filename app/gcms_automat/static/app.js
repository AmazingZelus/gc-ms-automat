// User interface logic. Plain JavaScript, no external libraries (works offline).
"use strict";

// ---- This reads the secret token from the address and creates a tab id ----
const TOKEN = new URLSearchParams(window.location.search).get("token") || "";
const CLIENT_ID = (crypto.randomUUID ? crypto.randomUUID()
  : String(Date.now()) + Math.random().toString(16).slice(2));
const HEARTBEAT_INTERVAL_MS = 5000;
let serverGone = false;     // true = this tab can never work again (quit or old key)
let infoLoaded = false;

// ---- This is a helper for calling the local API ----
async function api(path, body) {
  const options = {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-App-Token": TOKEN, "Content-Type": "application/json" },
  };
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (e) { /* not JSON */ }
  if (!response.ok || data.ok === false) {
    const error = new Error(data.error || ("Chyba serveru (" + response.status + ")"));
    error.status = response.status;
    throw error;
  }
  return data;
}

// ---- This shows or hides the "app is not running" banner ----
function setBanner(text) {
  const banner = document.getElementById("offline-banner");
  banner.hidden = !text;
  if (text) banner.textContent = text;
  document.querySelectorAll("button, select").forEach((el) => { el.disabled = Boolean(text); });
}

// ---- This marks the tab as permanently unusable (after Ukončit or with an old key) ----
function markServerGone(text) {
  serverGone = true;
  setBanner(text);
}

// ---- This tells the server every few seconds that this tab is still open ----
// A failed heartbeat (e.g. right after the computer wakes up) is NOT fatal:
// the banner is shown and the next heartbeat tries again.
async function sendHeartbeat() {
  if (serverGone) return;
  try {
    await api("/api/heartbeat", { cid: CLIENT_ID });
    setBanner("");
    if (!infoLoaded) loadInfo().catch(() => {});
  } catch (e) {
    if (e.status === 403) {
      // The key belongs to an earlier start of the app (e.g. the browser restored an old tab).
      markServerGone("Tato karta patří k dřívějšímu spuštění aplikace. Zavřete ji a použijte kartu, " +
        "kterou otevřel spustit.bat.");
    } else {
      setBanner("Aplikace neodpovídá. Pokud jste ji ukončili, spusťte znovu spustit.bat. " +
        "Jinak vyčkejte, zkouším se znovu připojit…");
    }
  }
}

// ---- This says goodbye when the tab is closed, so the server can stop ----
// sendBeacon is delivered even while the page is closing; it cannot send headers,
// so the token travels in the address.
function sayGoodbye() {
  const url = "/api/closing?token=" + encodeURIComponent(TOKEN) + "&cid=" + encodeURIComponent(CLIENT_ID);
  navigator.sendBeacon(url, "");
}

// ---- This loads the app name, version and library versions ----
async function loadInfo() {
  const info = await api("/api/info");
  if (infoLoaded) return;
  infoLoaded = true;
  document.title = info.app + " v" + info.version;
  document.getElementById("app-name").textContent = info.app;
  document.getElementById("app-version").textContent = "verze " + info.version;
  document.getElementById("exports-dir").textContent = info.exports_dir;

  const select = document.getElementById("csv-format");
  info.csv_formats.forEach((fmt) => {
    const option = document.createElement("option");
    option.value = fmt.key;
    option.textContent = fmt.label;
    option.selected = fmt.key === info.default_csv_format;
    select.appendChild(option);
  });

  const list = document.getElementById("lib-versions");
  const rows = [["Python", info.python]].concat(Object.entries(info.libraries));
  rows.forEach(([name, version]) => {
    const item = document.createElement("li");
    item.textContent = name + " " + version;
    list.appendChild(item);
  });
}

// ---- This is the "Export test" button ----
async function onExportClick() {
  const result = document.getElementById("export-result");
  result.className = "result";
  result.textContent = "Ukládám…";
  try {
    const data = await api("/api/export-test", { csv_format: document.getElementById("csv-format").value });
    result.classList.add("ok");
    result.textContent = "Uloženo: " + data.path;
  } catch (e) {
    result.classList.add("error");
    result.textContent = "Export se nepodařil: " + e.message;
  }
}

// ---- This is the "Otevřít složku s exporty" button ----
async function onOpenFolderClick() {
  try { await api("/api/open-exports", {}); }
  catch (e) { alert("Složku nelze otevřít: " + e.message); }
}

// ---- This is the "Ukončit" button ----
async function onQuitClick() {
  try { await api("/api/shutdown", {}); } catch (e) { /* server may already be gone */ }
  markServerGone("Aplikace byla ukončena. Tuto kartu můžete zavřít.");
}

// ---- This wires everything together when the page loads ----
document.getElementById("btn-export").addEventListener("click", onExportClick);
document.getElementById("btn-open-folder").addEventListener("click", onOpenFolderClick);
document.getElementById("btn-quit").addEventListener("click", onQuitClick);
window.addEventListener("pagehide", sayGoodbye);
// If the browser restores this page from its cache (Back button), reconnect at once.
window.addEventListener("pageshow", (event) => { if (event.persisted) sendHeartbeat(); });
// When the user comes back to this tab (e.g. after sleep), check the connection at once.
document.addEventListener("visibilitychange", () => { if (!document.hidden) sendHeartbeat(); });

sendHeartbeat();
setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
