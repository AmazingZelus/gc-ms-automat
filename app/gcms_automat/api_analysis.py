"""JSON API of the GC-MS analysis (used by the browser UI).

Every handler takes the session lock, so requests never see half-finished state.
Errors meant for the user are returned as {"ok": false, "error": "<Czech text>"}.
"""

from __future__ import annotations

import math
from functools import wraps

from flask import Blueprint, jsonify, request

from .analysis.params import PARAMETERS, AnalysisParams
from .analysis.table import EditError
from .session import ROLES, Session


def create_blueprint(session: Session) -> Blueprint:
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
        added, errors = [], []
        with session.lock:
            for f in request.files.getlist("files"):
                try:
                    added.append(session.add_file(f.filename or "soubor.CDF", f.read()))
                except ValueError as exc:
                    errors.append(f"{f.filename}: {exc}")
            if not session.alkanes and any(x.role == "alk" for x in session.files.values()):
                try:
                    session.auto_alkanes()
                except EditError:
                    pass
            return jsonify(ok=True, added=added, errors=errors, **state())

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
        session.update_params(body.get("params") or {})
        session.run()
        return {"table": session.table_json()} | state()

    @bp.post("/api/view")
    @handler
    def view(body):
        session.update_params(body.get("params") or {}, stage="view")
        return {"table": session.table_json()}

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
            row = a.set_window(int(body["uid"]), number(body["t0"], "t0"), number(body["t1"], "t1"))
            message, focus = "Okno použito.", row.uid
        elif action == "fill":
            row = a.fill_missing(int(body["uid"]))
            message, focus = row.edits[-1], row.uid
        elif action == "merge":
            row = a.merge([int(u) for u in body.get("uids", [])])
            message, focus = "Sloučeno.", row.uid
        elif action == "split":
            parts = a.split(int(body["uid"]), number(body["at"], "at"))
            message, focus = "Rozděleno na " + " a ".join(p.label for p in parts) + ".", parts[0].uid
        elif action == "delete":
            row = a.set_deleted(int(body["uid"]), bool(body.get("deleted", True)))
            message, focus = ("Řádek smazán." if row.deleted else "Řádek obnoven."), row.uid
        elif action == "note":
            row = a.set_note(int(body["uid"]), str(body.get("note", "")))
            message, focus = "Poznámka uložena.", row.uid
        else:
            raise EditError("Neznámá úprava.")
        return {"message": message, "focus": focus, "table": session.table_json()}

    @bp.post("/api/undo")
    @handler
    def undo(body):
        description = session.require().undo()
        return {"message": f"Vráceno: {description}.", "table": session.table_json()}

    return bp
