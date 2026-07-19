"""RDMP command-script emitter (prototype).

Emits one `Commands:` script per cohort group, mirroring the decompiled
`ExportCohortAsScript` format: catalogues referenced BY NAME (from the
binding), containers as SetContainerOperation INTERSECT/UNION/EXCEPT,
criteria as CreateNewFilter with the same WHERE SQL the SQL emitter builds
(unaliased). Anchored/sample criteria become correlated-subquery filters —
flagged in the header as the prototype recipe (a production build would use
an index-date/patient-index-table pattern instead).
"""
import registry as R
import requirement_schema as S

from .binding import src, catalogue
from .ir import DRAFT_BANNER, build_ir, oneline, precheck, provenance
from .sqlgen import leaf_where

OP_NAME = {"and": "INTERSECT", "or": "UNION"}


def _dq(s):
    """Escape a value for an RDMP double-quoted command argument. Control
    characters are collapsed first (a newline inside an argument would start
    a new command line), then backslashes and quotes are escaped."""
    return oneline(s).replace("\\", "\\\\").replace('"', '\\"')


class _Vars:
    def __init__(self):
        self.c = 0
        self.a = 0

    def container(self):
        self.c += 1
        return f"$c{self.c}"

    def aggregate(self):
        self.a += 1
        return f"$a{self.a}"


def _leaf_cmds(leaf, parent, binding, v, cmds):
    source = "biobank_samples" if leaf["kind"] == "sample" else leaf["source"]
    cat = catalogue(src(binding, source))
    agg = v.aggregate()
    cmds.append(f'AddCatalogueToCohortIdentificationSetContainer '
                f'CohortAggregateContainer:{parent} Catalogue:"{_dq(cat)}"   # => {agg}')
    where = " AND ".join(leaf_where(leaf, binding, alias=""))
    name = leaf.get("label") or f"{leaf['kind']} {leaf.get('id', '')}".strip()
    cmds.append(f'CreateNewFilter AggregateConfiguration:{agg} '
                f'"{_dq(name)}" "{_dq(where)}"')


def _container_cmds(expr, parent, binding, v, cmds):
    for child in expr[1]:
        if child[0] == "leaf":
            if child[1].get("kind") == "note":     # draft mode only (precheck blocks otherwise)
                cmds.append(f'# TODO (draft): unresolved note criterion '
                            f'{oneline(child[1].get("id"))} '
                            f'"{_dq(child[1].get("label", ""))}" — NOT built')
                continue
            _leaf_cmds(child[1], parent, binding, v, cmds)
        else:
            sub = v.container()
            cmds.append(f'AddCohortSubContainer CohortAggregateContainer:{parent}   # => {sub}')
            cmds.append(f'SetContainerOperation CohortAggregateContainer:{sub} {OP_NAME[child[0]]}')
            _container_cmds(child, sub, binding, v, cmds)


def _group_cmds(g, binding):
    v = _Vars()
    cmds = [f'CreateNewCohortIdentificationConfiguration "{_dq(g["name"])}"']
    expr = g["expr"]
    inclusion, exclusions = expr[1], expr[2]
    root = v.container()
    if exclusions:
        cmds.append(f'SetContainerOperation CohortAggregateContainer:{root} EXCEPT   # root')
        inc = v.container()
        cmds.append(f'AddCohortSubContainer CohortAggregateContainer:{root}   # => {inc} (inclusion)')
        cmds.append(f'SetContainerOperation CohortAggregateContainer:{inc} {OP_NAME[inclusion[0]]}')
        _container_cmds(inclusion, inc, binding, v, cmds)
        for i, e in enumerate(exclusions, 1):
            if e[0] == "leaf":
                e = ("and", [e])                   # every EXCEPT sibling is a container
            sub = v.container()
            cmds.append(f'AddCohortSubContainer CohortAggregateContainer:{root}   '
                        f'# => {sub} (exclusion {i}, subtracted in order)')
            cmds.append(f'SetContainerOperation CohortAggregateContainer:{sub} {OP_NAME[e[0]]}')
            _container_cmds(e, sub, binding, v, cmds)
    else:
        cmds.append(f'SetContainerOperation CohortAggregateContainer:{root} '
                    f'{OP_NAME[inclusion[0]]}   # root (no exclusions)')
        _container_cmds(inclusion, root, binding, v, cmds)
    return cmds


def compile_rdmp(contract, binding, draft=False):
    """[{id, name, script}] — one RDMP command script per cohort group."""
    precheck(contract, binding, draft=draft)
    out = []
    for g in build_ir(contract):
        lines = []
        if draft and S.notes_in(contract):
            lines.append(f"# {DRAFT_BANNER}")
        lines += [f"# cohort group: {oneline(g['name'])} (id {oneline(g['id'])})",
                  f"# {provenance(contract, binding)}",
                  "# prototype emitter: anchored/sample criteria are emitted as",
                  "# correlated-subquery filters; a production build would use an",
                  "# index-date table (PIT) pattern instead.",
                  "Commands:"]
        lines += [f"- {c}" if not c.startswith("#") else f"  {c}"
                  for c in _group_cmds(g, binding)]
        out.append({"id": g["id"], "name": g["name"], "script": "\n".join(lines) + "\n"})
    return out
