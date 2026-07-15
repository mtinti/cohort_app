"""Site binding manifests — PHYSICAL mapping only.

A binding maps logical registry sources to a site's local tables/columns. It
can never alter matching or expansion semantics (those are registry-owned);
a site either implements a source or declares it unsupported by omitting it.

Shape (binding.<site>.yaml):

    binding_version: 1
    site: <name>
    sources:
      <logical source>:
        table: <local table>            # required
        catalogue: <RDMP catalogue>     # optional; defaults to table
        patient_id_column: <col>        # required
        date_column: <col>              # required for event-shaped sources
        code_columns: {<vocab>: <col>}  # codes/anchor sources
        columns: {age: <col>, sex: <col>}          # demographics
        measures:                        # measure sources
          <measure>: {filter_column: <col>, filter_value: <val>, value_column: <col>}
"""
import yaml

import registry as R

_BINDING_KEYS = {"binding_version", "site", "sources"}
_SOURCE_KEYS = {"table", "catalogue", "patient_id_column", "date_column",
                "code_columns", "columns", "measures"}
BINDING_VERSION = 1


class CompileError(Exception):
    """Raised when a contract cannot be compiled; carries the problem list."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def load_binding(path):
    with open(path) as f:
        b = yaml.safe_load(f)
    problems = check_binding(b)
    if problems:
        raise CompileError([f"binding {path}: {p}" for p in problems])
    return b


def check_binding(b):
    """Structural check of a binding dict. [] = ok."""
    errs = []
    if not isinstance(b, dict):
        return ["binding must be a YAML mapping"]
    extra = set(b) - _BINDING_KEYS
    if extra:
        errs.append("unknown field(s): " + ", ".join(sorted(extra)))
    if b.get("binding_version") != BINDING_VERSION:
        errs.append(f"unsupported binding_version {b.get('binding_version')!r} "
                    f"(supported: {BINDING_VERSION})")
    if not b.get("site"):
        errs.append("site name is required")
    srcs = b.get("sources")
    if not isinstance(srcs, dict) or not srcs:
        errs.append("sources must be a non-empty mapping")
        return errs
    for name, s in srcs.items():
        where = f"source '{name}'"
        if name not in R.SOURCES:
            errs.append(f"{where}: not a registry source (a binding cannot invent "
                        "sources — extend sources.yaml instead)")
            continue
        if not isinstance(s, dict):
            errs.append(f"{where}: must be a mapping")
            continue
        extra = set(s) - _SOURCE_KEYS
        if extra:
            errs.append(f"{where}: unknown field(s): " + ", ".join(sorted(extra)))
        for req_field in ("table", "patient_id_column"):
            if not s.get(req_field):
                errs.append(f"{where}: {req_field} is required")
        for vocab in (s.get("code_columns") or {}):
            if vocab not in R.VOCABULARIES:
                errs.append(f"{where}: code_columns names unknown vocabulary '{vocab}'")
        for m, spec in (s.get("measures") or {}).items():
            if m not in R.measures_for(name):
                errs.append(f"{where}: measure '{m}' is not in the registry for this source")
            elif not isinstance(spec, dict) or not spec.get("value_column"):
                errs.append(f"{where}: measure '{m}' needs at least value_column")
    return errs


def src(binding, name):
    return (binding.get("sources") or {}).get(name)


def catalogue(sb):
    """RDMP catalogue name for a bound source (defaults to the table name)."""
    return sb.get("catalogue") or sb["table"]
