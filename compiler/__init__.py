"""Deterministic contract compiler: (contract + site binding) -> executable script.

Pipeline (fail-closed, see plan.md §3.5): strict gate (level 1, schema shape)
-> registry conformance (level 2) -> no `note` leaves -> site feasibility
(level 3) -> IR -> emitter. Any failure raises CompileError with the full
problem list; nothing is ever silently dropped or weakened.

Emitters:
  * sqlgen  — portable SQL (SQLite-compatible); also the CI test harness.
  * rdmpgen — an RDMP-style `Commands:` script (prototype; mirrors the
              decompiled ExportCohortAsScript format).

The only allowed escape hatch is draft=True, which tolerates `note` leaves but
prefixes the output with a line that makes it non-executable by construction.
"""
from .binding import CompileError, load_binding, check_binding
from .feasibility import check_feasibility
from .ir import build_ir, precheck
from .sqlgen import compile_sql
from .rdmpgen import compile_rdmp

__all__ = ["CompileError", "load_binding", "check_binding", "check_feasibility",
           "build_ir", "precheck", "compile_sql", "compile_rdmp"]
