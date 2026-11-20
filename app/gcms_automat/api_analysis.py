"""JSON API of the GC-MS analysis (used by the browser UI).

Every handler takes the session lock, so requests never see half-finished state.
Errors meant for the user are returned as {"ok": false, "error": "<Czech text>"}.
"""

from __future__ import annotations

import math
from functools import wraps

from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from .analysis.params import PARAMETERS, AnalysisParams
from .analysis.table import EditError
from .paths import EXPORTS_DIR
from .session import ROLES, Session
from .xlsx_export import ExportOptions, build_workbook, save_workbook


def create_blueprint(session: Session, exports_dir: Path = EXPORTS_DIR) -> Blueprint:
    bp = Blueprint("analysis", __name__)

    # ---- This wraps handlers: lock, JSON body, user-facing errors ----
    def handler(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            body = request.get_json(silent=True)
            body = body if isinstance(body, dict) else {}
            with session.lock:
                try:
                    result = func(body, *args, **kwargs)
                except EditError as exc:
                    return jsonify(ok=False, error=str(exc)), 400
                except (ValueError, KeyError, TypeError) as exc:
                    return jsonify(ok=False, error=f"Neplatný požadavek: {exc}"), 400
            return jsonify(ok=True, **(result or {}))
        return wrapped

    def uid_list(value):
        if not isinstance(value, list) or not all(isinstance(u, int) and not isinstance(u, bool) for u in value):
            raise EditError("Seznam řádků musí být seznam čísel.")
        return value

    def flag(value):
        if not isinstance(value, bool):
            raise EditError("Očekávám true/false.")
        return value

    def number(value, name):
        x = float(value)
        if not math.isfinite(x):
            raise ValueError(f"{name} není číslo")
        return x

    def state():
        return {"files": session.files_json(), "alkanes": session.alkanes_json(), "params": session.params.to_dict(),
                "defaults": AnalysisParams().to_dict(), "dirty": session.dirty, "has_result": session.analysis is not None}

    # ---- This describes the parameters (the UI builds its form from it) ----
    @bp.get("/api/params-meta")
    @handler
    def params_meta(body):
        return {"params": [vars(p) for p in PARAMETERS]}

    @bp.get("/api/state")
    @handler
    def get_state(body):
        return state()

    # ---- This receives uploaded .CDF files ----
    @bp.post("/api/files")
    def upload():
        added, replaced, errors = [], [], []
        with session.lock:
            for f in request.files.getlist("files"):
                try:
                    name, was_there = session.add_file(f.filename or "soubor.CDF", f.read())
                    (replaced if was_there or name in added else added).append(name)
                except Exception as exc:  # any broken file is reported, the others still load
                    errors.append(f"{f.filename}: {exc}")
            if not session.alkanes and any(x.role == "alk" for x in session.files.values()):
                try:
                    session.auto_alkanes()
                except EditError:
                    pass
            return jsonify(ok=True, added=added, replaced=replaced, errors=errors, **state())

    @bp.post("/api/files/role")
    @handler
    def set_role(body):
        if body.get("role") not in ROLES:
            raise EditError("Neznámá role.")
        session.set_role(str(body.get("name")), body["role"])
        return state()

    @bp.post("/api/files/remove")
    @handler
    def remove_file(body):
        session.remove_file(str(body.get("name")))
        return state()

    # ---- Alkanes for the retention index ----
    @bp.post("/api/alkanes")
    @handler
    def set_alkanes(body):
        session.set_alkanes(body.get("alkanes") or [])
        return state()

    @bp.post("/api/alkanes/auto")
    @handler
    def auto_alkanes(body):
        n = session.auto_alkanes()
        return state() | {"message": f"Nalezeno {n} alkanů. Zkontroluj je."}

    @bp.post("/api/alkanes/import")
    @handler
    def import_alkanes(body):
        n = session.import_alkanes(str(body.get("text", "")))
        return state() | {"message": f"Načteno {n} alkanů."}

    # ---- Computation and table ----
    @bp.post("/api/run")
    @handler
    def run(body):
        rejected = session.update_params(body.get("params") or {})
        session.run()
        return {"table": session.table_json(), "rejected": rejected} | state()

    @bp.post("/api/view")
    @handler
    def view(body):
        rejected = session.update_params(body.get("params") or {}, stage="view")
        return {"table": session.table_json(), "rejected": rejected, "params": session.params.to_dict()}

    @bp.get("/api/table")
    @handler
    def table(body):
        return {"table": session.table_json()}

    @bp.get("/api/detail")
    @handler
    def detail(body):
        uid = int(request.args["uid"])
        return session.detail_json(uid, number(request.args["t0"], "t0"), number(request.args["t1"], "t1"))

    @bp.get("/api/spectrum")
    @handler
    def spectrum(body):
        return session.spectrum_json(int(request.args["uid"]), request.args.get("sample", ""))

    # ---- Manual edits (all refuse to create overlapping windows) ----
    @bp.post("/api/edit")
    @handler
    def edit(body):
        a = session.require()
        action = body.get("action")
        if action == "window":
            samples = body.get("samples")
            if samples is not None and (not isinstance(samples, list) or not all(isinstance(x, str) for x in samples)):
                raise EditError("Seznam vzorků musí být seznam názvů.")
            row, clipped = a.set_window(int(body["uid"]), number(body["t0"], "t0"), number(body["t1"], "t1"), samples)
            message = "Okno použito" + (" (jen " + ", ".join(samples) + ")" if samples else "") + "."
            if clipped:
                message += " Oříznuto u sousedního řádku ve: " + ", ".join(clipped) + "."
            focus = row.uid
        elif action == "fill":
            row = a.fill_missing(int(body["uid"]))
            message, focus = row.edits[-1], row.uid
        elif action == "merge":
            row = a.merge(uid_list(body.get("uids")))
            message, focus = "Sloučeno.", row.uid
        elif action == "split":
            parts = a.split(int(body["uid"]), number(body["at"], "at"))
            message, focus = "Rozděleno na " + " a ".join(p.label for p in parts) + ".", parts[0].uid
        elif action == "delete":
            row = a.set_deleted(int(body["uid"]), flag(body.get("deleted", True)))
            message, focus = ("Řádek smazán." if row.deleted else "Řádek obnoven."), row.uid
        elif action == "note":
            row = a.set_note(int(body["uid"]), str(body.get("note", "")))
            message, focus = "Poznámka uložena.", row.uid
        else:
            raise EditError("Neznámá úprava.")
        return {"message": message, "focus": focus, "table": session.table_json()}

    # ---- Excel export of the current result ----
    @bp.post("/api/export")
    @handler
    def export(body):
        a = session.require()
        raw = body.get("options") or {}
        options = ExportOptions(
            # Missing key = the UI default (ND sheet); an explicit empty list = no area sheet.
            markers=[str(x) for x in raw["markers"]] if isinstance(raw.get("markers"), list) else ["nd"],
            custom_text=str(raw.get("custom_text", ""))[:200],
            mean_formats=[str(x) for x in raw.get("mean_formats", [])] if isinstance(raw.get("mean_formats"), list) else [],
            mean_missing=str(raw.get("mean_missing", "nd")),
            only_visible=raw.get("only_visible", True) is not False,
            provenance=raw.get("provenance", True) is not False,
        )
        try:
            options.validate()
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        workbook = build_workbook(a, session.export_params(), a.alkanes, session.result_files, options,
                                  computed_at=session.computed_at, changed_since=session.dirty)
        try:
            path = save_workbook(workbook, exports_dir)
        except OSError as exc:
            raise EditError(f"Soubor nejde uložit do složky exporty ({exc}). Není složka jen pro čtení?") from exc
        return {"filename": path.name, "path": str(path)}

    # ---- Download of a file from the exports folder (plain file name only) ----
    @bp.get("/api/download")
    def download():
        name = request.args.get("name", "")
        if not name or name != Path(name).name or name.endswith(".part") or not (exports_dir / name).is_file():
            return jsonify(ok=False, error="Soubor nenalezen."), 404
        return send_from_directory(exports_dir, name, as_attachment=True)

    @bp.post("/api/undo")
    @handler
    def undo(body):
        description = session.require().undo()
        return {"message": f"Vráceno: {description}.", "table": session.table_json()}

    return bp
