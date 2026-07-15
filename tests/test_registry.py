"""Level-2 validation: registry conformance (sources.yaml)."""
import registry as R
import requirement_schema as S


def test_registry_loads():
    assert R.REGISTRY_VERSION == 1
    assert "codes" in R.SOURCES["hospital_admissions"]["kinds"]
    assert R.sources_for("demographic") == ["demographics"]
    assert "icd10" in R.vocabs_for("hospital_admissions")
    assert "hba1c" in R.measures_for("lab_results")


def test_example_conforms_to_registry():
    assert R.check_sources(S.to_contract(S.build_example())) == []


def test_unknown_source_flagged():
    c = S.to_contract(S.build_example())
    c["cohorts"][0]["inclusion"]["members"][0]["source"] = "mystery_db"
    assert any("not in the registry" in e for e in R.check_sources(c))


def test_illegal_vocab_for_source_flagged():
    c = S.to_contract(S.build_example())
    # BNF codes on a hospital (ICD-only) source
    for m in c["cohorts"][0]["inclusion"]["members"][1]["members"]:
        if m.get("source") == "hospital_admissions":
            m["bnf"] = ["0601"]
    assert any("'bnf'" in e and "not legal" in e for e in R.check_sources(c))


def test_wrong_kind_for_source_flagged():
    c = S.to_contract(S.build_example())
    c["cohorts"][0]["inclusion"]["members"][0]["source"] = "prescribing"  # demographic leaf
    assert any("does not support kind 'demographic'" in e for e in R.check_sources(c))


def test_unknown_measure_flagged():
    req = S.from_contract({
        "project": "x", "project_type": "recruitment",
        "schema_version": S.SCHEMA_VERSION,
        "cohorts": [{"id": "g", "name": "G", "exclusions": [], "inclusion": {
            "id": "c", "op": "AND", "members": [
                {"id": "m", "kind": "measure", "source": "lab_results",
                 "measure": "cholesterol_special", "op": ">", "value": 5}]}}]})
    errs = R.check_sources(S.to_contract(req))
    assert any("cholesterol_special" in e for e in errs)


def test_bad_anchor_source_flagged():
    c = S.to_contract(S.build_example())
    c["cohorts"][0]["inclusion"]["members"][1]["members"][0]["when"] = {
        "anchor": {"event": {"source": "demographics", "vocab": "read", "codes": ["X"]},
                   "direction": "before"}}
    assert any("cannot be used as an anchor" in e for e in R.check_sources(c))
