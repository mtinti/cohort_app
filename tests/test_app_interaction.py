"""Playwright interaction tests: drive the real Streamlit app in a browser.

Proves the flows screenshots can't: the form serializes through the real
download button, add-group works, the leaf dialog adds a condition, reorder
swaps exclusion order, and validation reacts to a blank requirement.
"""
import re

import yaml

import requirement_schema as S
from conftest import settle


def download_yaml(page):
    with page.expect_download() as di:
        page.get_by_role("button", name="Download YAML").click()
    return yaml.safe_load(open(di.value.path()))


def strip_ids(o):
    """Drop persistent `id`s (random per session) to compare content only."""
    if isinstance(o, dict):
        return {k: strip_ids(v) for k, v in o.items() if k != "id"}
    if isinstance(o, list):
        return [strip_ids(v) for v in o]
    return o


def test_app_loads_example(page):
    assert page.get_by_text("INCLUSION — base population").is_visible()
    # both example groups present in the sidebar selector
    assert page.get_by_role("radio", name="Group B", exact=False).count() >= 1


def test_yaml_preview_popup(page):
    page.get_by_role("button", name=re.compile("Preview YAML")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    assert dlg.count() == 1
    assert "project:" in dlg.inner_text()


def test_default_download_matches_contract(page):
    got = download_yaml(page)
    assert strip_ids(got) == strip_ids(S.to_contract(S.build_example()))
    assert S.check_contract(got) == []          # the app's own export passes the gate


def test_add_group(page):
    # the example has no plain "Group 3" (it's "Group 3 — …"); adding makes one
    assert page.get_by_role("radio", name="Group 3", exact=True).count() == 0
    page.get_by_role("button", name=re.compile(r"Add$")).click()   # sidebar "➕ Add"
    settle(page)
    assert page.get_by_role("radio", name="Group 3", exact=True).count() == 1


def test_clone_group(page):
    before = len(download_yaml(page)["cohorts"])
    page.get_by_role("button", name=re.compile(r"Clone")).click()
    settle(page)
    after = download_yaml(page)["cohorts"]
    assert len(after) == before + 1
    assert any(c["name"].endswith("(copy)") for c in after)


def test_add_inclusion_button(page):
    before = len(download_yaml(page)["cohorts"][0]["inclusion"]["members"])
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    # source is now a registry dropdown (default = first codes-capable source)
    dlg.get_by_role("textbox", name="ICD-10").fill("Z01")
    page.keyboard.press("Tab"); settle(page)
    dlg.get_by_role("button", name="Save").click(); settle(page)
    after = download_yaml(page)["cohorts"][0]["inclusion"]["members"]
    assert len(after) == before + 1
    assert any(m.get("source") == "hospital_admissions" and m.get("icd") == ["Z01"]
               for m in after)


def test_add_subgroup_via_container_button(page):
    # the container's own ➕ (exact, not the sidebar "➕ Add") adds into THAT group
    before = len(download_yaml(page)["cohorts"][0]["inclusion"]["members"])
    page.get_by_role("button", name="➕", exact=True).first.click()   # root inclusion container
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("INTERSECT")).click()
    settle(page)
    after = len(download_yaml(page)["cohorts"][0]["inclusion"]["members"])
    assert after == before + 1


def test_add_exclusion_via_dialog(page):
    page.get_by_role("button", name=re.compile(r"Add exclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Label").fill("Test exclusion")
    dlg.get_by_role("textbox", name="ICD-10").fill("Z99")
    page.keyboard.press("Tab")
    settle(page)
    dlg.get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    excls = got["cohorts"][0]["exclusions"]
    assert any(e.get("label") == "Test exclusion" and e.get("icd") == ["Z99"]
               for e in excls)


def test_add_exclusion_container_via_dialog(page):
    before = len(download_yaml(page)["cohorts"][0]["exclusions"])
    page.get_by_role("button", name=re.compile(r"Add exclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("UNION")).click()
    settle(page)
    assert page.locator("[data-testid='stException']").count() == 0
    excl = download_yaml(page)["cohorts"][0]["exclusions"]
    assert len(excl) == before + 1
    assert any("op" in e for e in excl)            # a container was added (not a condition)


def test_reorder_exclusion(page):
    before = download_yaml(page)["cohorts"][0]["exclusions"]
    assert len(before) >= 2
    # click the first exclusion's down-arrow (first ↓ button on the page)
    page.get_by_role("button", name="↓").first.click()
    settle(page)
    after = download_yaml(page)["cohorts"][0]["exclusions"]
    assert [e.get("label") for e in after[:2]] == [
        before[1].get("label"), before[0].get("label")]


def test_load_yaml_populates_form(page, tmp_path):
    f = tmp_path / "loaded.requirement.yaml"
    f.write_text(
        "project: Loaded Project\nproject_type: recruitment\ntarget_n: '42'\n"
        "schema_version: 1\ncohorts:\n  - name: Loaded Group\n    inclusion:\n"
        "      op: AND\n      members:\n        - kind: codes\n          label: x\n"
        "          source: GP\n          read: [A1]\n    exclusions: []\n")
    page.get_by_text("Load a requirement.yaml").click()      # open the expander
    settle(page)
    page.locator("input[type='file']").set_input_files(str(f))
    settle(page)
    assert page.get_by_role("textbox", name="Title").input_value() == "Loaded Project"
    got = download_yaml(page)
    assert got["project"] == "Loaded Project"
    assert got["cohorts"][0]["name"] == "Loaded Group"
    # the file has no persistent ids -> loads fine but is flagged as a DRAFT
    assert page.get_by_text("does not pass the strict contract gate").is_visible()


def test_blank_requirement_shows_validation(page):
    page.get_by_role("button", name="New (blank requirement)").click()
    settle(page)
    assert page.get_by_text("Not ready").is_visible()
    got = download_yaml(page)
    assert got["project"] == ""


def test_seal_contract_flow(page):
    page.get_by_text("📜 Contract header").click()      # open the expander
    settle(page)
    page.get_by_role("button", name=re.compile("Seal as agreed")).click()
    settle(page)
    assert page.get_by_text("hash ✓ body unchanged since sealing").is_visible()
    got = download_yaml(page)
    assert got["contract"]["status"] == "agreed"
    assert S.hash_status(got) == "ok"
    assert S.check_contract(got) == []
    # editing the body after sealing is detected (the sidebar banner refreshes
    # on the NEXT rerun — it renders before the main-area edit lands, so
    # trigger one more rerun via a second edit)
    page.get_by_role("textbox", name="Group name").fill("Tampered name")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("textbox", name="Target N").fill("999")
    page.keyboard.press("Tab")
    settle(page)
    assert page.get_by_text("body CHANGED since sealing").is_visible()
    assert S.hash_status(download_yaml(page)) == "changed"


def test_vocab_fields_follow_source(page):
    # editing the example 'Condition in hospital data' leaf (icd=[A00]):
    # ✎ order in the tree: root, Adults, OR container, hospital codes, ...
    page.get_by_role("button", name="✎").nth(3).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    assert dlg.get_by_role("textbox", name="ICD-10").count() == 1
    # switch source hospital_admissions -> prescribing (2nd combobox; 1st is Kind)
    dlg.locator("[data-baseweb='select']").nth(1).click()
    settle(page, 400)
    page.get_by_role("option", name="prescribing").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    # only the legal vocab fields are editable now…
    assert dlg.get_by_role("textbox", name="ICD-10").count() == 0
    assert dlg.get_by_role("textbox", name="BNF").count() == 1
    assert dlg.get_by_role("textbox", name="Drug names").count() == 1
    # …and the carried-over ICD codes are surfaced, never silently dropped
    assert "not legal" in dlg.inner_text()
    dlg.get_by_role("button", name="🗑 Remove the ICD-10 codes").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    assert "not legal" not in dlg.inner_text()
    dlg.get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    leaf = got["cohorts"][0]["inclusion"]["members"][1]["members"][0]
    assert leaf["source"] == "prescribing" and "icd" not in leaf
