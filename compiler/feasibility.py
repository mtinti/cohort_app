"""Level-3 validation: can site X execute contract Y? Static, no data access.

Walks every criterion (by persistent id) and checks the site binding provides
the physical columns the criterion needs. Returns a list of problem strings,
each prefixed with the criterion id — [] means feasible.
"""
import registry as R

from .binding import src

# single definition lives in the registry (also used by check_sources + the UI)
EVENT_TYPE_VOCAB = R.EVENT_TYPE_VOCAB


def _need(sb, source, field, where, errs, sub=None):
    if sb is None:
        errs.append(f"{where}: source '{source}' is not bound at this site")
        return False
    val = sb.get(field)
    if sub is not None:
        val = (val or {}).get(sub)
    if not val:
        errs.append(f"{where}: source '{source}' binding has no "
                    + (f"{field}.{sub}" if sub else field))
        return False
    return True


def _check_anchor_feasible(anchor, binding, where, errs):
    ev = (anchor or {}).get("event") or {}
    esrc, vocab = ev.get("source"), ev.get("vocab")
    esb = src(binding, esrc)
    if _need(esb, esrc, "date_column", where + " (anchor)", errs):
        _need(esb, esrc, "code_columns", where + " (anchor)", errs, sub=vocab)


def _check_when_feasible(leaf, sb, binding, where, errs):
    w = leaf.get("when") or {}
    if (w.get("window") or w.get("anchor")) and sb is not None:
        _need(sb, leaf.get("source"), "date_column", where, errs)
    if w.get("anchor"):
        _check_anchor_feasible(w["anchor"], binding, where, errs)


def check_feasibility(contract, binding):
    """[] = site can execute every criterion of the contract."""
    errs = []

    def leaf(d, where):
        k = d.get("kind")
        where = f"criterion {d.get('id', '?')} ({where})"
        if k == "note":
            errs.append(f"{where}: `note` criteria are never executable — resolve "
                        "into coded criteria first")
            return
        if k == "sample":
            se = d.get("sample_event") or {}
            ev = se.get("event") or {}
            sb = src(binding, "biobank_samples")
            if _need(sb, "biobank_samples", "date_column", where, errs):
                pass
            etype = ev.get("type")
            if etype == "lab_result":
                errs.append(f"{where}: lab_result sample events are free text and "
                            "not yet compilable")
                return
            esrc = R.EVENT_SOURCE.get(etype)
            esb = src(binding, esrc)
            if _need(esb, esrc, "date_column", where, errs):
                _need(esb, esrc, "code_columns", where, errs,
                      sub=EVENT_TYPE_VOCAB.get(etype))
            return
        source = d.get("source")
        sb = src(binding, source)
        if sb is None:
            errs.append(f"{where}: source '{source}' is not bound at this site")
            return
        if k == "demographic":
            if d.get("age_min") is not None or d.get("age_max") is not None:
                _need(sb, source, "columns", where, errs, sub="age")
            if d.get("sex") in ("female", "male"):
                _need(sb, source, "columns", where, errs, sub="sex")
            for f in ("residence", "simd"):
                if d.get(f):
                    errs.append(f"{where}: '{f}' criteria are not yet compilable "
                                "(free text)")
        elif k == "codes":
            for field, vocab in R.VOCAB_FIELDS.items():
                if d.get(field):
                    _need(sb, source, "code_columns", where, errs, sub=vocab)
            _check_when_feasible(d, sb, binding, where, errs)
        elif k == "measure":
            _need(sb, source, "measures", where, errs, sub=d.get("measure"))
            _check_when_feasible(d, sb, binding, where, errs)

    def member(d, where):
        if not isinstance(d, dict):
            return
        if d.get("kind"):
            leaf(d, where)
        else:
            for m in d.get("members") or []:
                member(m, where)

    for g in (contract or {}).get("cohorts") or []:
        gname = g.get("name", "?")
        member(g.get("inclusion") or {}, f"group '{gname}'")
        for m in g.get("exclusions") or []:
            member(m, f"group '{gname}' exclusions")
    return errs
