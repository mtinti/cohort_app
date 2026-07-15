"""IR + the fail-closed precheck shared by every emitter.

The IR is a deliberately minimal set-algebra tree (plan.md §3.5) that grows
primitive-by-primitive with the schema:

    group  := ("except", inclusion_expr, [subtracted_expr, ...])   # ordered
    expr   := ("and"|"or", [expr, ...]) | ("leaf", <raw leaf dict>)

Leaves keep their raw contract dict — predicate typing happens in the
emitters, which share the WHERE-builder in sqlgen.
"""
import registry as R
import requirement_schema as S

from .binding import CompileError, check_binding
from .feasibility import check_feasibility

DRAFT_BANNER = "!! NON-EXECUTABLE DRAFT — contains unresolved `note` criteria !!"


def precheck(contract, binding, draft=False):
    """Run validation levels 1-3 + the no-notes rule. Raises CompileError."""
    problems = ["[gate] " + e for e in S.check_contract(contract)]
    problems += ["[registry] " + e for e in R.check_sources(contract)]
    problems += ["[binding] " + e for e in check_binding(binding)]
    notes = S.notes_in(contract)
    if notes and not draft:
        problems += [f"[notes] criterion {i} ('{lbl}'): `note` criteria never "
                     "compile — resolve into coded criteria, or use draft mode "
                     "for a non-executable preview" for i, lbl in notes]
    if not problems:            # feasibility is only meaningful on a sane input
        feas = check_feasibility(contract, binding)
        if draft:               # notes were allowed above; don't double-report
            feas = [p for p in feas if "`note` criteria" not in p]
        problems += ["[feasibility] " + e for e in feas]
    if problems:
        raise CompileError(problems)


def _expr(d):
    if d.get("kind"):
        return ("leaf", d)
    op = "and" if d.get("op", "AND") == "AND" else "or"
    return (op, [_expr(m) for m in d.get("members") or []])


def build_ir(contract):
    """[{id, name, expr}] — one entry per cohort group (= one build)."""
    return [{"id": g["id"], "name": g["name"],
             "expr": ("except", _expr(g["inclusion"]),
                      [_expr(m) for m in g.get("exclusions") or []])}
            for g in contract["cohorts"]]


def provenance(contract, binding):
    hdr = contract.get("contract") or {}
    return (f"contract {hdr.get('id', '(unsealed)')} "
            f"v{hdr.get('version', '?')} sha256:{(hdr.get('body_sha256') or '')[:12] or 'n/a'}"
            f" | schema v{contract.get('schema_version')}"
            f" | registry v{R.REGISTRY_VERSION}"
            f" | binding {binding.get('site')} v{binding.get('binding_version')}")
