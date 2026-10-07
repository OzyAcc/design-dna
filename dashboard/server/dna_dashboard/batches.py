"""Batch composer: products x template versions -> stable pairs -> resolved, independently editable outputs.

Copy precedence per text slot (later explicit values win; an empty string is a deliberate value, None = no override):
    template defaults (frozen in the version)  ->  batch defaults (by slot role)  ->  product overrides (by role)
    ->  pair overrides (bulk-applied, by slot id)  ->  manual output overrides (typed in the output editor, by slot id)
Hard locks and required slots stay binding whatever the layer. AI drafts are proposals stored beside the pair; they
become a manual override only through an explicit "use draft" action and stay unapproved until a person approves.
A pair id is derived from (batch, product, template, variant index), so it is independent of row order and a pair
removed and re-added to the same draft keeps its content.
"""
from __future__ import annotations

import hashlib
import json

from . import db
from . import templates_svc as ts
from .errors import AppError, conflict, not_found

IMAGE_ROLES = ("product", "hero", "photo", "image", "packshot", "main")
MODES = ("adapt", "creative", "creative_slot")
LANGS = ("en", "ar")


def pair_id(batch_id, product_id, template_id, vi=0) -> str:
    return "pa_" + hashlib.sha1(f"{batch_id}|{product_id}|{template_id}|{vi}".encode()).hexdigest()[:16]


def get(conn, bid) -> dict:
    b = db.one(conn, "SELECT * FROM batches WHERE id = ?", (bid,))
    if not b:
        raise not_found("batch draft", bid)
    return b


def pairs(conn, bid) -> list[dict]:
    return db.all_(conn, "SELECT * FROM batch_pairs WHERE batch_id = ? ORDER BY created_at, variant_index", (bid,))


def product(conn, pid) -> dict:
    p = db.one(conn, "SELECT * FROM products WHERE id = ?", (pid,))
    if not p:
        raise not_found("product", pid)
    return p


def create(conn, name="Untitled batch", template_versions=None, product_ids=None, defaults=None) -> dict:
    bid = db.new_id("bt")
    db.insert(conn, "batches", {"id": bid, "name": name, "template_versions": template_versions or [], "product_ids": product_ids or [],
                                "defaults": defaults or {"mode": "adapt", "language": "en", "copy": {}, "instructions": ""},
                                "product_overrides": {}, "created_at": db.now(), "updated_at": db.now()})
    sync_pairs(conn, get(conn, bid))
    return get(conn, bid)


def update(conn, bid, base_revision: int, changes: dict) -> dict:
    with db.tx(conn):
        b = get(conn, bid)
        if base_revision != b["revision"]:
            raise conflict("this batch draft changed in another tab; reload before saving", "stale_batch", current_revision=b["revision"])
        upd = {"revision": b["revision"] + 1, "updated_at": db.now()}
        if "name" in changes:
            upd["name"] = str(changes["name"] or "Untitled batch")[:120]
        if "template_versions" in changes:
            tv = []
            for x in changes["template_versions"]:
                v = ts.version(conn, x["version_id"])
                if v["template_id"] != x["template_id"]:
                    raise AppError("that version does not belong to that template", "bad_version")
                tv.append({"template_id": x["template_id"], "version_id": x["version_id"]})
            upd["template_versions"] = tv
        if "product_ids" in changes:
            for pid in changes["product_ids"]:
                product(conn, pid)
            upd["product_ids"] = list(dict.fromkeys(changes["product_ids"]))
        if "defaults" in changes:
            d = dict(b["defaults"] or {})
            for k, v in (changes["defaults"] or {}).items():
                if k == "mode" and v not in MODES:
                    raise AppError(f"unknown mode {v!r}", "bad_mode")
                if k == "language" and v not in LANGS:
                    raise AppError(f"unsupported language {v!r}", "bad_language")
                if k == "copy":
                    d["copy"] = _merge(d.get("copy") or {}, v or {})
                else:
                    d[k] = v
            upd["defaults"] = d
        if "product_overrides" in changes:
            po = dict(b["product_overrides"] or {})
            for pid, v in (changes["product_overrides"] or {}).items():
                cur = dict(po.get(pid) or {})
                if "copy" in (v or {}):
                    cur["copy"] = _merge(cur.get("copy") or {}, v["copy"] or {})
                if "instructions" in (v or {}):
                    cur["instructions"] = v["instructions"]
                po[pid] = cur
            upd["product_overrides"] = po
        db.update(conn, "batches", bid, upd)
        sync_pairs(conn, get(conn, bid))
    return get(conn, bid)


def _merge(cur: dict, new: dict) -> dict:
    """None removes an override; any string (including "") sets it."""
    out = dict(cur)
    for k, v in new.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = str(v)
    return out


def sync_pairs(conn, b: dict) -> None:
    """Ensure one pair per selected product x template; detach (never delete) pairs that left the selection."""
    sel = {(pid, x["template_id"]): x["version_id"] for pid in b["product_ids"] for x in b["template_versions"]}
    existing = pairs(conn, b["id"])
    seen = set()
    for p in existing:
        key = (p["product_id"], p["template_id"])
        want = sel.get(key)
        upd = {}
        if want is None:
            if p["attached"]:
                upd["attached"] = 0
        else:
            seen.add(key)
            if not p["attached"]:
                upd["attached"] = 1
            if want != p["template_version_id"]:
                chk = version_change(conn, p, want)
                if chk["auto"]:
                    upd.update(template_version_id=want, version_check=chk)
                else:
                    upd["version_check"] = chk
        if upd:
            upd["updated_at"] = db.now()
            db.update(conn, "batch_pairs", p["id"], upd)
    for (pid, tid), vid in sel.items():
        if (pid, tid) in seen:
            continue
        db.insert(conn, "batch_pairs", {"id": pair_id(b["id"], pid, tid, 0), "batch_id": b["id"], "product_id": pid, "template_id": tid,
                                        "template_version_id": vid, "variant_index": 0, "created_at": db.now(), "updated_at": db.now()})


def version_change(conn, p: dict, new_vid: str) -> dict:
    old = ts.version(conn, p["template_version_id"])
    new = ts.version(conn, new_vid)
    old_slots = {s["id"]: s for s in old["summary"]["slots"]}
    new_slots = {s["id"]: s for s in new["summary"]["slots"]}
    used = set(p.get("pair_overrides") or {}) | set(p.get("manual") or {}) | set(p.get("ai_drafts") or {})
    missing = sorted(k for k in used if k not in new_slots)
    changed = sorted(k for k in used if k in new_slots and (new_slots[k]["role"], new_slots[k]["type"]) != (old_slots.get(k, {}).get("role"), old_slots.get(k, {}).get("type")))
    return {"from": old["id"], "from_number": old["number"], "to": new["id"], "to_number": new["number"], "missing_slots": missing,
            "changed_slots": changed, "added_slots": sorted(set(new_slots) - set(old_slots)), "auto": not missing and not changed,
            "needs_confirmation": bool(missing or changed), "at": db.now()}


def confirm_version(conn, bid, pid, mapping: dict) -> dict:
    """Apply a pending version change to a pair: content of each old slot moves to the slot the user mapped it to, or is
    dropped (mapping value null). Nothing is remapped without this explicit step."""
    with db.tx(conn):
        p = get_pair(conn, bid, pid)
        chk = p.get("version_check") or {}
        if not chk.get("needs_confirmation"):
            raise AppError("this output has no pending template version change", "nothing_to_confirm")
        new_slots = {s["id"] for s in ts.version(conn, chk["to"])["summary"]["slots"]}
        po, man, drafts = dict(p["pair_overrides"] or {}), dict(p["manual"] or {}), dict(p["ai_drafts"] or {})
        for old in chk["missing_slots"] + chk["changed_slots"]:
            dest = mapping.get(old)
            if dest is not None and dest not in new_slots:
                raise AppError(f"{dest!r} is not a slot of the new version", "bad_mapping")
            for store in (po, man, drafts):
                if old in store:
                    val = store.pop(old)
                    if dest:
                        store[dest] = val
        db.update(conn, "batch_pairs", pid, {"template_version_id": chk["to"], "pair_overrides": po, "manual": man, "ai_drafts": drafts,
                                             "version_check": dict(chk, needs_confirmation=False, confirmed_at=db.now(), mapping=mapping),
                                             "updated_at": db.now()})
    return get_pair(conn, bid, pid)


def get_pair(conn, bid, pid) -> dict:
    p = db.one(conn, "SELECT * FROM batch_pairs WHERE id = ? AND batch_id = ?", (pid, bid))
    if not p:
        raise not_found("output pairing", pid)
    return p


def set_pair(conn, bid, pid, changes: dict) -> dict:
    with db.tx(conn):
        p = get_pair(conn, bid, pid)
        upd = {"updated_at": db.now()}
        if "included" in changes:
            upd["included"] = 1 if changes["included"] else 0
        if "mode" in changes:
            if changes["mode"] not in (None,) + MODES:
                raise AppError(f"unknown mode {changes['mode']!r}", "bad_mode")
            upd["mode"] = changes["mode"]
        if "language" in changes:
            if changes["language"] not in (None,) + LANGS:
                raise AppError(f"unsupported language {changes['language']!r}", "bad_language")
            upd["language"] = changes["language"]
        if "instructions" in changes:
            upd["instructions"] = changes["instructions"]
        if "manual" in changes:
            man = dict(p["manual"] or {})
            for slot, v in (changes["manual"] or {}).items():
                if v is None:
                    man.pop(slot, None)
                else:
                    val = v.get("value") if isinstance(v, dict) else v
                    src = (v.get("source") if isinstance(v, dict) else None) or "manual"
                    approved = True if src == "manual" else bool(v.get("approved")) if isinstance(v, dict) else True
                    man[slot] = {"value": "" if val is None else str(val), "source": src, "approved": approved, "at": db.now()}
            upd["manual"] = man
        db.update(conn, "batch_pairs", pid, upd)
    return get_pair(conn, bid, pid)


def use_ai_draft(conn, bid, pid, slot_id) -> dict:
    p = get_pair(conn, bid, pid)
    d = (p.get("ai_drafts") or {}).get(slot_id)
    if not d:
        raise AppError("there is no AI draft for that slot", "no_draft")
    return set_pair(conn, bid, pid, {"manual": {slot_id: {"value": d["value"], "source": "ai", "approved": False}}})


def approve_slot(conn, bid, pid, slot_id) -> dict:
    with db.tx(conn):
        p = get_pair(conn, bid, pid)
        man = dict(p["manual"] or {})
        if slot_id not in man:
            raise AppError("nothing to approve for that slot", "nothing_to_approve")
        man[slot_id] = dict(man[slot_id], approved=True, approved_at=db.now())
        db.update(conn, "batch_pairs", pid, {"manual": man, "updated_at": db.now()})
    return get_pair(conn, bid, pid)


def add_variant(conn, bid, product_id, template_id) -> dict:
    with db.tx(conn):
        b = get(conn, bid)
        base = db.one(conn, "SELECT * FROM batch_pairs WHERE batch_id = ? AND product_id = ? AND template_id = ? AND variant_index = 0",
                      (bid, product_id, template_id))
        if not base:
            raise AppError("select the product and template first", "not_selected")
        vi = conn.execute("SELECT MAX(variant_index) FROM batch_pairs WHERE batch_id = ? AND product_id = ? AND template_id = ?",
                          (bid, product_id, template_id)).fetchone()[0] + 1
        pid = pair_id(b["id"], product_id, template_id, vi)
        db.insert(conn, "batch_pairs", {"id": pid, "batch_id": bid, "product_id": product_id, "template_id": template_id,
                                        "template_version_id": base["template_version_id"], "variant_index": vi, "created_at": db.now(),
                                        "updated_at": db.now()})
    return get_pair(conn, bid, pid)


def bulk_apply(conn, bid, scope: dict, copy: dict | None = None, instructions: str | None = None) -> dict:
    """Apply values to all outputs (batch defaults), one product (product overrides), or one template / selected rows
    (pair overrides, mapped from slot role to each pair's own slot ids). Manual output overrides are never touched."""
    kind = scope.get("kind")
    copy = copy or {}
    if kind == "all":
        b = get(conn, bid)
        ch = {"defaults": {"copy": copy}} if copy else {}
        if instructions is not None:
            ch.setdefault("defaults", {})["instructions"] = instructions
        return update(conn, bid, b["revision"], ch)
    if kind == "product":
        b = get(conn, bid)
        v = {}
        if copy:
            v["copy"] = copy
        if instructions is not None:
            v["instructions"] = instructions
        return update(conn, bid, b["revision"], {"product_overrides": {scope["product_id"]: v}})
    with db.tx(conn):
        targets = pairs(conn, bid)
        if kind == "template":
            targets = [p for p in targets if p["template_id"] == scope["template_id"]]
        elif kind == "pairs":
            ids = set(scope.get("pair_ids") or [])
            targets = [p for p in targets if p["id"] in ids]
        else:
            raise AppError("scope must be all, product, template or pairs", "bad_scope")
        for p in targets:
            slots = ts.version(conn, p["template_version_id"])["summary"]["slots"]
            po = dict(p["pair_overrides"] or {})
            for role, val in copy.items():
                for s in slots:
                    if s["type"] == "text" and s["role"] == role:
                        if val is None:
                            po.pop(s["id"], None)
                        else:
                            po[s["id"]] = {"value": str(val), "at": db.now()}
            upd = {"pair_overrides": po, "updated_at": db.now()}
            if instructions is not None:
                upd["instructions"] = instructions
            db.update(conn, "batch_pairs", p["id"], upd)
    return get(conn, bid)


# ------------------------------------------------------------------ resolution + preflight
def resolve(conn, b: dict, p: dict, providers_ok: dict | None = None) -> dict:
    v = ts.version(conn, p["template_version_id"])
    s = v["summary"]
    prod = product(conn, p["product_id"])
    t = ts.get(conn, p["template_id"])
    defaults = b.get("defaults") or {}
    po_prod = (b.get("product_overrides") or {}).get(p["product_id"]) or {}
    mode = p.get("mode") or defaults.get("mode") or "adapt"
    lang = p.get("language") or defaults.get("language") or "en"
    tdef = (s.get("defaults") or {}).get("copy") or {}
    problems, warnings, slots = [], [], []
    for sl in s["slots"]:
        if sl["type"] != "text":
            continue
        val, src = None, None
        layers = (("template default", tdef.get(sl["id"])), ("batch default", (defaults.get("copy") or {}).get(sl["role"])),
                  ("product override", (po_prod.get("copy") or {}).get(sl["role"])),
                  ("pair override", ((p.get("pair_overrides") or {}).get(sl["id"]) or {}).get("value")))
        for name, layer_val in layers:
            if layer_val is not None:
                val, src = layer_val, name
        man = (p.get("manual") or {}).get(sl["id"])
        approved = True
        if man is not None:
            val, src, approved = man["value"], ("AI draft" if man.get("source") == "ai" else "manual"), man.get("approved", True)
        entry = {"slot_id": sl["id"], "role": sl["role"], "node": sl["node"], "value": val, "source": src, "approved": approved,
                 "required": sl["required"], "locked": sl.get("locked") or [], "limits": sl.get("limits") or {},
                 "template_text": sl.get("template_text"), "ai_draft": (p.get("ai_drafts") or {}).get(sl["id"]), "hidden": False, "problems": []}
        if sl.get("locked"):
            if val is not None and val != sl.get("template_text"):
                entry["problems"].append(f"locked by the template ({', '.join(sl['locked'])}); its text cannot change")
            val = entry["value"] = sl.get("template_text")
            entry["source"] = "locked template text"
        elif val is None:
            if sl["required"]:
                entry["problems"].append("no copy supplied for a required slot (the reference's text is design evidence, not product copy)")
            else:
                entry["hidden"] = True
                warnings.append(f"{sl['role']}: no copy supplied; the slot will be hidden")
        elif val == "":
            if sl["required"]:
                entry["problems"].append("a required slot cannot be empty")
            else:
                entry["hidden"] = True
        if val:
            lim = entry["limits"]
            chars = len(val.replace("\n", ""))
            if lim.get("max_chars") and chars > lim["max_chars"]:
                entry["problems"].append(f"{chars} characters; the slot allows {lim['max_chars']}")
            if lim.get("max_lines") and val.count("\n") + 1 > lim["max_lines"]:
                entry["problems"].append(f"{val.count(chr(10)) + 1} lines; the slot allows {lim['max_lines']} (rewrite, or edit a template copy)")
        if man is not None and man.get("source") == "ai" and not approved:
            entry["problems"].append("AI draft not approved yet: review it, edit or approve")
        problems += [f"{sl['role']}: {x}" for x in entry["problems"]]
        slots.append(entry)
    image_slots = [x for x in s["slots"] if x["type"] == "image"]
    primary = next((x for x in image_slots if x["role"] in IMAGE_ROLES), image_slots[0] if image_slots else None)
    image = None
    if primary:
        image = {"slot_id": primary["id"], "node": primary["node"], "role": primary["role"], "asset_id": prod.get("primary_asset_id"),
                 "locked": primary.get("locked") or []}
        if primary.get("locked"):
            problems.append(f"{primary['role']}: the image slot is locked by the template")
        for x in image_slots:
            if x is not primary:
                warnings.append(f"{x['role']}: keeps the reference image (design evidence from the original)")
    logos = [x for x in s["slots"] if x["type"] == "logo"]
    if logos:
        warnings.append("reference logo hidden: no brand transfers to a new output unless you supply one")
    elig = s.get("eligibility") or {}
    if not prod.get("primary_asset_id") and (mode != "adapt" or primary):
        problems.append("the product has no primary image")
    if mode == "adapt":
        if not elig.get("adapt", {}).get("eligible"):
            problems += [f"editable adaptation unavailable: {r}" for r in elig.get("adapt", {}).get("reasons", [])]
        warnings += elig.get("adapt", {}).get("limitations", [])
        if not primary:
            warnings.append("the template has no image slot: the product photo is not used in editable adaptation")
    else:
        if providers_ok is not None and not providers_ok.get("image_generation"):
            problems.append("no image generation provider is configured (Settings)")
        if mode == "creative_slot" and not primary:
            problems.append("creative slot imagery needs a template with an image slot")
        warnings.append("creative generation produces a new image: no pixel preservation or editability is claimed")
    font = None
    if lang == "ar":
        fsha = defaults.get("arabic_font")
        if not fsha:
            problems.append("Arabic needs a font that covers its glyphs: choose one in the batch settings")
        else:
            from . import enginelib as el

            font = next((f for f in el.font_library() if f["sha256"] == fsha), None)
            if not font:
                problems.append("the chosen Arabic font is no longer in the font library")
            else:
                for e in slots:
                    if e["value"] and not e["hidden"] and not el.covers(font["path"], e["value"]):
                        problems.append(f"{e['role']}: {font['names'].get('full')} lacks glyphs for this text")
    if p.get("version_check", {}) and (p.get("version_check") or {}).get("needs_confirmation"):
        problems.append("the selected template version changed and some slots differ: confirm how to map this output's copy")
    instr = [x for x in ((s.get("defaults") or {}).get("instructions"), defaults.get("instructions"), po_prod.get("instructions"),
                         prod.get("instructions"), p.get("instructions")) if x]
    resolved = {"pair_id": p["id"], "mode": mode, "language": lang, "slots": slots, "image": image,
                "logos_hidden": [x["node"] for x in logos], "instructions": instr, "arabic_font": font and {"sha256": font["sha256"], "names": font["names"]},
                "template": {"id": t["id"], "name": t["name"], "version_id": v["id"], "number": v["number"], "bundle_sha256": v["bundle_sha256"],
                             "readiness": v["readiness"], "canvas": s["canvas"]},
                "product": {"id": prod["id"], "name": prod["name"], "description": prod["description"], "facts": prod["facts"],
                            "primary_asset_id": prod["primary_asset_id"], "detail_asset_ids": prod["detail_asset_ids"]}}
    resolved["inputs_hash"] = hashlib.sha256(json.dumps({k: resolved[k] for k in ("mode", "language", "slots", "image", "arabic_font", "template")},
                                                        sort_keys=True, default=str).encode()).hexdigest()[:16]
    prev = p.get("preview") or {}
    fit = prev.get("fit") if prev.get("inputs_hash") == resolved["inputs_hash"] else None
    resolved["fit"] = fit
    resolved["preview"] = prev if prev.get("inputs_hash") == resolved["inputs_hash"] else ({"stale": True} if prev else None)
    if mode == "adapt" and fit and fit.get("status") == "overflow":
        problems.append("the copy does not fit: " + "; ".join(f"{k}: {x}" for k, x in (fit.get("overflow") or {}).items())[:300])
    resolved["problems"], resolved["warnings"] = problems, sorted(set(warnings))
    resolved["status"] = "error" if problems else ("warning" if warnings else "ready")
    return resolved


def providers_status() -> dict:
    from .providers import ProviderError, for_capability

    out = {}
    for cap in ("analysis", "copy", "image_generation"):
        try:
            p = for_capability(cap)
            out[cap] = {"provider": p.name, "mock": p.mock}
        except ProviderError:
            out[cap] = None
    return out


def matrix(conn, bid) -> dict:
    b = get(conn, bid)
    pv = providers_status()
    rows = []
    for p in pairs(conn, bid):
        if not p["attached"]:
            continue
        try:
            r = resolve(conn, b, p, pv)
        except AppError as e:
            r = {"pair_id": p["id"], "status": "error", "problems": [e.message], "warnings": []}
        rows.append(dict(r, included=bool(p["included"]), variant_index=p["variant_index"], product_id=p["product_id"],
                         template_id=p["template_id"], template_version_id=p["template_version_id"],
                         version_check=p.get("version_check"), pair_mode=p.get("mode"), pair_language=p.get("language"),
                         pair_instructions=p.get("instructions")))
    inc = [r for r in rows if r["included"]]
    return {"batch": public(b), "pairs": rows, "providers": pv,
            "counts": {"proposed": len(rows), "included": len(inc), "excluded": len(rows) - len(inc),
                       "blocked": sum(1 for r in inc if r["status"] == "error")},
            "detached": [p["id"] for p in pairs(conn, bid) if not p["attached"]]}


def public(b: dict) -> dict:
    return {k: b.get(k) for k in ("id", "name", "status", "revision", "template_versions", "product_ids", "defaults", "product_overrides",
                                  "run_id", "created_at", "updated_at")}


def submit(conn, bid, idempotency_key: str, name: str | None = None) -> dict:
    from . import jobs

    if not idempotency_key or len(idempotency_key) > 120:
        raise AppError("an idempotency key is required to submit", "missing_idempotency_key")
    prev = db.one(conn, "SELECT * FROM runs WHERE idempotency_key = ?", (idempotency_key,))
    if prev:
        return {"run_id": prev["id"], "duplicate": True}
    m = matrix(conn, bid)
    inc = [r for r in m["pairs"] if r["included"]]
    if not inc:
        raise AppError("no outputs are included", "nothing_to_generate")
    blocked = [{"pair_id": r["pair_id"], "problems": r["problems"]} for r in inc if r["status"] == "error"]
    if blocked:
        raise conflict("some outputs cannot be generated yet; fix the listed problems or exclude them", "preflight_failed", blocked=blocked)
    with db.tx(conn):
        prev = db.one(conn, "SELECT * FROM runs WHERE idempotency_key = ?", (idempotency_key,))
        if prev:
            return {"run_id": prev["id"], "duplicate": True}
        b = get(conn, bid)
        rid = db.new_id("rn")
        snap = {"batch": public(b), "outputs": inc, "submitted_at": db.now()}
        db.insert(conn, "runs", {"id": rid, "batch_id": bid, "name": name or b["name"], "idempotency_key": idempotency_key, "snapshot": snap,
                                 "created_at": db.now()})
        for r in inc:
            oid = db.new_id("op")
            db.insert(conn, "outputs", {"id": oid, "run_id": rid, "pair_id": r["pair_id"], "product_id": r["product"]["id"],
                                        "template_id": r["template"]["id"], "template_version_id": r["template"]["version_id"], "mode": r["mode"],
                                        "language": r["language"], "inputs": r, "status": "queued", "created_at": db.now(), "updated_at": db.now()})
            j = jobs.enqueue(conn, "output.generate", {"output_id": oid}, idempotency_key=f"{rid}:{r['pair_id']}:1", run_id=rid, output_id=oid,
                             batch_id=bid, priority=5)
            db.update(conn, "outputs", oid, {"job_id": j["id"]})
        db.update(conn, "batches", bid, {"run_id": rid, "updated_at": db.now()})
    return {"run_id": rid, "duplicate": False, "outputs": len(inc)}
