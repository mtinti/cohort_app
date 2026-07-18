"""Compiler tests: same contract + two different site bindings -> the SAME
patients on identically-seeded synthetic data (the plan's headline success
criterion), plus fail-closed behaviour and the RDMP emitter's structure.
"""
import os
import sqlite3
import subprocess
import sys

import pytest
import yaml

import requirement_schema as S
from compiler import (CompileError, check_feasibility, compile_rdmp,
                      compile_sql, load_binding)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples")

# --- one logical dataset, loaded into BOTH site shapes ----------------------
# patients: (id, age, sex)
DEMOG = [(1, 30, "female"), (2, 40, "male"), (3, 70, "female"), (4, 10, "male"),
         (5, 50, "female"), (6, 60, "male"), (7, 45, "female"), (8, 85, "male")]
# (pid, icd diagnosis, opcs procedure, date) — site B stores procedures WITH
# the dot (L29.4) while site A is dotless (L294): the registry's strip_dots
# normalization must make both match a contract code either way
HOSP = [(1, "A001", "L294", "2019-02-01"), (2, "B001", None, "2019-03-01"),
        (3, "A00", "K634", "2018-05-01"), (5, "J45", None, "2020-01-01"),
        (8, "A00", None, "2019-01-01")]
GP = [(2, "X1111", "2019-01-01"), (6, "X1111", "2019-06-01"), (4, "X1111", "2019-04-01")]
RX = [(1, "0101", "Metformin", "2019-02-10"), (5, "0202", "METFORMIN", "2019-07-01"),
      (7, "06011", "Aspirin", "2019-08-01"), (6, "0601", "Statin", "2019-03-01"),
      (3, "0601", "Statin", "2019-05-01")]
LABS = [(1, "HBA1C", 47, "2019-01-15"), (3, "HBA1C", 50, "2018-06-01"),
        (5, "HBA1C", 49, "2019-03-01"), (6, "HBA1C", 55, "2019-02-01")]
SAMPLES = [(2, "2018-12-01"), (6, "2020-01-01")]


def make_db(binding):
    """Create an in-memory DB shaped by the binding, seeded with the data."""
    conn = sqlite3.connect(":memory:")
    s = binding["sources"]

    def create(src, cols, rows):
        b = s[src]
        conn.execute(f"CREATE TABLE {b['table']} ({', '.join(cols)})")
        if rows:
            ph = ", ".join("?" * len(cols))
            conn.executemany(f"INSERT INTO {b['table']} VALUES ({ph})", rows)

    d = s["demographics"]
    create("demographics",
           [d["patient_id_column"], d["columns"]["age"], d["columns"]["sex"]], DEMOG)
    h = s["hospital_admissions"]
    hosp = HOSP
    if binding["site"] == "site-b":                  # dotted procedure codes
        hosp = [(p, icd, (op[:3] + "." + op[3:] if op else op), d)
                for p, icd, op, d in HOSP]
    create("hospital_admissions",
           [h["patient_id_column"], h["code_columns"]["icd10"],
            h["code_columns"]["opcs4"], h["date_column"]], hosp)
    g = s["gp_events"]
    create("gp_events",
           [g["patient_id_column"], g["code_columns"]["read"], g["date_column"]], GP)
    r = s["prescribing"]
    create("prescribing",
           [r["patient_id_column"], r["code_columns"]["bnf"],
            r["code_columns"]["drug_name"], r["date_column"]], RX)
    lb = s["lab_results"]
    m = lb["measures"]["hba1c"]
    create("lab_results",
           [lb["patient_id_column"], m["filter_column"], m["value_column"],
            lb["date_column"]], LABS)
    bs = s["biobank_samples"]
    create("biobank_samples", [bs["patient_id_column"], bs["date_column"]], SAMPLES)
    de = s["deaths"]
    create("deaths",
           [de["patient_id_column"], de["code_columns"]["icd10"], de["date_column"]], [])
    return conn


@pytest.fixture(scope="module")
def sites():
    out = []
    for name in ("site-a", "site-b"):
        b = load_binding(os.path.join(EX, f"binding.{name}.yaml"))
        out.append((b, make_db(b)))
    return out


def contract(name):
    with open(os.path.join(EX, f"requirement.{name}.yaml")) as f:
        return yaml.safe_load(f)


def cohorts(contract_dict, binding, conn):
    return {r["name"]: {row[0] for row in conn.execute(r["sql"].rstrip(";\n"))}
            for r in compile_sql(contract_dict, binding)}


# --- parity + hand-computed membership --------------------------------------
EXPECTED = {
    "case-control": {"Cases": {1, 3, 6}, "Controls": {5, 7}},
    "drug-recruitment": {"Exposed adults": {5, 7}},
    "temporal-measure": {"Anchored threshold cohort": {6}},
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_same_cohort_at_both_sites(sites, name):
    c = contract(name)
    results = [cohorts(c, b, conn) for b, conn in sites]
    assert results[0] == results[1] == EXPECTED[name]


def test_sample_kind_compiles_and_runs(sites):
    # person has >=1 biobank sample BEFORE their first coded GP event
    req = S.new_requirement()
    req["project"] = "sample test"
    g = req["cohorts"][0]
    g["name"] = "Sampled"
    g["inclusion"]["members"].append(
        S.new_sample("has sample before first diagnosis", event_type="gp_data",
                     occurrence="first", codes=["X1111"], direction="before"))
    c = S.to_contract(req)
    assert S.check_contract(c) == []
    results = [cohorts(c, b, conn)["Sampled"] for b, conn in sites]
    assert results[0] == results[1] == {2}


# --- fail-closed -------------------------------------------------------------
def test_notes_block_compilation(sites):
    c = contract("case-control")
    c["cohorts"][0]["exclusions"].append(
        {"id": "n1", "kind": "note", "label": "unresolved", "text": "no code yet"})
    binding, _ = sites[0]
    with pytest.raises(CompileError) as e:
        compile_sql(c, binding)
    assert any("[notes]" in p for p in e.value.problems)
    # draft mode compiles but the first line makes the output non-executable
    out = compile_sql(c, binding, draft=True)
    assert out[0]["sql"].startswith("!! NON-EXECUTABLE DRAFT")
    conn = sites[0][1]
    with pytest.raises(sqlite3.OperationalError):
        conn.execute(out[0]["sql"])


def test_gate_failure_blocks_compilation(sites):
    c = contract("case-control")
    c["schema_version"] = 99
    with pytest.raises(CompileError) as e:
        compile_sql(c, sites[0][0])
    assert any("[gate]" in p and "schema_version" in p for p in e.value.problems)


def test_uncompilable_fields_block(sites):
    c = contract("case-control")
    # residence is recorded in the contract but not compilable -> feasibility
    for m in c["cohorts"][0]["inclusion"]["members"]:
        if m.get("kind") == "demographic":
            m["residence"] = "somewhere"
    with pytest.raises(CompileError) as e:
        compile_sql(c, sites[0][0])
    assert any("[feasibility]" in p and "residence" in p for p in e.value.problems)


def codes_contract(**fields):
    """Single group, single codes leaf on hospital_admissions."""
    return {"project": "x", "project_type": "recruitment", "target_n": "",
            "schema_version": S.SCHEMA_VERSION,
            "cohorts": [{"id": "g1", "name": "G", "exclusions": [], "inclusion": {
                "id": "c1", "op": "AND", "members": [
                    {"id": "l1", "kind": "codes", "label": "c",
                     "source": "hospital_admissions", **fields}]}}]}


def test_chapter_letter_is_a_prefix(sites):
    results = [cohorts(codes_contract(icd=["A"]), b, conn)["G"] for b, conn in sites]
    assert results[0] == results[1] == {1, 3, 8}


def test_cross_letter_block_range(sites):
    # ICD-10 chapters cross letters (e.g. C00-D48); spans compare strings
    results = [cohorts(codes_contract(icd=["A00-B01"]), b, conn)["G"]
               for b, conn in sites]
    assert results[0] == results[1] == {1, 2, 3, 8}


def test_subcategory_dot_normalized(sites):
    # contract says A00.1; the data stores A001 — strip_dots matches them
    results = [cohorts(codes_contract(icd=["A00.1"]), b, conn)["G"]
               for b, conn in sites]
    assert results[0] == results[1] == {1}


def test_opcs_category_matches_dotted_and_dotless_sites(sites):
    # site A stores L294, site B stores L29.4 — same cohort either way
    c = codes_contract(opcs=["L29"])
    import registry as RG
    assert S.check_contract(c) == [] and RG.check_sources(c) == []
    results = [cohorts(c, b, conn)["G"] for b, conn in sites]
    assert results[0] == results[1] == {1}


def test_invalid_code_form_blocks_compilation(sites):
    # F02.31 is deeper than the allowed subcategory depth -> registry level
    with pytest.raises(CompileError) as e:
        compile_sql(codes_contract(icd=["F02.31"]), sites[0][0])
    assert any("[registry]" in p and "invalid ICD-10" in p for p in e.value.problems)
    with pytest.raises(CompileError) as e:          # descending range
        compile_sql(codes_contract(icd=["D48-C00"]), sites[0][0])
    assert any("D48-C00" in p for p in e.value.problems)


def test_icd_numeric_range_expands(sites):
    c = contract("case-control")
    for m in c["cohorts"][0]["inclusion"]["members"][1]["members"]:
        if m.get("icd"):
            m["icd"] = ["A00-01"]           # covers the A00/A001 rows
    results = [cohorts(c, b, conn)["Cases"] for b, conn in sites]
    assert results[0] == results[1] == {1, 3, 6}


# --- feasibility (level 3) ---------------------------------------------------
def test_feasibility_reports_unbound_source_by_criterion_id():
    c = contract("temporal-measure")
    binding = load_binding(os.path.join(EX, "binding.site-a.yaml"))
    del binding["sources"]["lab_results"]
    problems = check_feasibility(c, binding)
    measure_id = c["cohorts"][0]["inclusion"]["members"][0]["id"]
    assert any(measure_id in p and "lab_results" in p for p in problems)
    with pytest.raises(CompileError):
        compile_sql(c, binding)


def test_binding_cannot_invent_sources():
    binding = load_binding(os.path.join(EX, "binding.site-a.yaml"))
    binding["sources"]["shadow_db"] = {"table": "x", "patient_id_column": "id"}
    from compiler import check_binding
    assert any("cannot invent sources" in p for p in check_binding(binding))


# --- RDMP emitter (structural) -----------------------------------------------
def test_rdmp_script_structure(sites):
    binding, _ = sites[0]
    out = compile_rdmp(contract("case-control"), binding)
    cases = next(r for r in out if r["name"] == "Cases")["script"]
    assert "Commands:" in cases
    assert 'CreateNewCohortIdentificationConfiguration "Cases"' in cases
    assert "SetContainerOperation CohortAggregateContainer:$c1 EXCEPT" in cases
    assert 'Catalogue:"HospitalAdmissions"' in cases       # by NAME, from binding
    assert 'Catalogue:"Demography"' in cases
    # registry prefix semantics, dot-normalized on the data side
    assert "REPLACE(icd_code, '.', '') LIKE 'A00%'" in cases
    hdr = (contract("case-control").get("contract") or {})
    assert "registry v2" in cases and "binding site-a" in cases   # provenance
    controls = next(r for r in out if r["name"] == "Controls")["script"]
    assert "EXCEPT" in controls                            # exclusions -> root EXCEPT
    # site-b emits the same structure with ITS catalogue names
    b2 = load_binding(os.path.join(EX, "binding.site-b.yaml"))
    cases_b = next(r for r in compile_rdmp(contract("case-control"), b2)
                   if r["name"] == "Cases")["script"]
    assert 'Catalogue:"SITEB_SMR01"' in cases_b
    assert "REPLACE(main_condition, '.', '') LIKE 'A00%'" in cases_b


def test_rdmp_no_exclusions_root_is_inclusion_op(sites):
    binding, _ = sites[0]
    out = compile_rdmp(contract("temporal-measure"), binding)
    assert "SetContainerOperation CohortAggregateContainer:$c1 INTERSECT" in out[0]["script"]
    assert "EXCEPT" not in out[0]["script"]


# --- CLI ----------------------------------------------------------------------
def test_cli_check_and_compile(tmp_path):
    env = {**os.environ, "PYTHONPATH": ROOT}
    r = subprocess.run(
        [sys.executable, "-m", "compiler",
         os.path.join(EX, "requirement.case-control.yaml"),
         os.path.join(EX, "binding.site-a.yaml"), "--check"],
        capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
    r = subprocess.run(
        [sys.executable, "-m", "compiler",
         os.path.join(EX, "requirement.case-control.yaml"),
         os.path.join(EX, "binding.site-b.yaml"),
         "--target", "rdmp", "--out", str(tmp_path)],
        capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 0, r.stderr
    written = list(tmp_path.iterdir())
    assert len(written) == 2                                # one script per group
    assert all(f.name.endswith(".commands.yaml") for f in written)
