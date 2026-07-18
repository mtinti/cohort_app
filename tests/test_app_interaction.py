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
    page.get_by_text("FINALIZE CONTRACT").click()      # open the expander
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


# ---------------------------------------------------------------------------
# Dialog editing — every kind, timing, container ops, remove/cancel
# ---------------------------------------------------------------------------
def pick(page, dlg, nth, option):
    """Choose `option` in the nth baseweb selectbox of the dialog."""
    dlg.locator("[data-baseweb='select']").nth(nth).click()
    settle(page, 400)
    page.get_by_role("option", name=option, exact=True).click()
    settle(page)
    return page.get_by_role("dialog")


def test_kind_options_exclude_sample_by_default(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.locator("[data-baseweb='select']").nth(0).click()      # Kind
    settle(page, 400)
    opts = [o.inner_text() for o in page.get_by_role("option").all()]
    assert opts == ["demographic", "codes", "measure", "note"]
    page.keyboard.press("Escape")


def test_edit_demographic_leaf(page):
    page.get_by_role("button", name="✎").nth(1).click()        # 'Adults'
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Age max").fill("70")
    dlg.get_by_text("female", exact=True).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    leaf = download_yaml(page)["cohorts"][0]["inclusion"]["members"][0]
    assert leaf["age_max"] == 70 and leaf["sex"] == "female"


def test_edit_container_op(page):
    page.get_by_role("button", name="✎").nth(2).click()        # OR 'Condition of interest'
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_text("INTERSECT — all of (AND)").click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    assert got["cohorts"][0]["inclusion"]["members"][1]["op"] == "AND"


def test_remove_condition(page):
    before = download_yaml(page)["cohorts"][0]["inclusion"]["members"]
    page.get_by_role("button", name="✕").first.click()         # 'Adults'
    settle(page)
    after = download_yaml(page)["cohorts"][0]["inclusion"]["members"]
    assert len(after) == len(before) - 1
    assert all(m.get("kind") != "demographic" for m in after)


def test_cancel_keeps_state(page):
    before = download_yaml(page)
    page.get_by_role("button", name="✎").nth(1).click()        # 'Adults'
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Label").fill("changed label")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    settle(page)
    assert download_yaml(page) == before


def test_add_measure_condition(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = pick(page, page.get_by_role("dialog"), 0, "measure")  # Kind -> measure
    dlg.get_by_role("textbox", name="Value").fill("48")
    dlg.get_by_role("textbox", name="Unit").fill("mmol/mol")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    leaf = got["cohorts"][0]["inclusion"]["members"][-1]
    assert leaf == {"id": leaf["id"], "kind": "measure", "source": "lab_results",
                    "measure": "hba1c", "op": ">=", "value": 48, "unit": "mmol/mol"}
    assert S.check_contract(got) == []


def test_codes_window_timing(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="ICD-10").fill("E11")
    dlg.get_by_text("⏱ Timing (optional)").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Window from (YYYY-MM-DD)").fill("2019-01-01")
    dlg.get_by_role("textbox", name="Window to (YYYY-MM-DD)").fill("2020-12-31")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    leaf = got["cohorts"][0]["inclusion"]["members"][-1]
    assert leaf["when"]["window"] == {"from": "2019-01-01", "to": "2020-12-31"}
    assert S.check_contract(got) == []


def test_codes_anchor_timing(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="ICD-10").fill("E11")
    dlg.get_by_text("⏱ Timing (optional)").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_text("Anchor to a per-patient index event").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Event codes (one per line)").fill("X1")
    dlg.get_by_role("textbox", name="Within N (blank = any time)").fill("6")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    anchor = got["cohorts"][0]["inclusion"]["members"][-1]["when"]["anchor"]
    assert anchor["event"]["source"] == "hospital_admissions"   # first anchor source
    assert anchor["event"]["vocab"] == "icd10"
    assert anchor["event"]["codes"] == ["X1"]
    assert anchor["direction"] == "before"
    assert anchor["within"] == {"n": 6, "unit": "months"}
    assert S.check_contract(got) == []


# ---------------------------------------------------------------------------
# Group management + validation banners
# ---------------------------------------------------------------------------
def test_duplicate_group_name_flagged(page):
    other = download_yaml(page)["cohorts"][1]["name"]
    page.get_by_role("textbox", name="Group name").fill(other)
    page.keyboard.press("Tab")
    settle(page)
    assert page.get_by_text("used more than once").is_visible()


def test_remove_group_and_disabled_at_one(page):
    assert len(download_yaml(page)["cohorts"]) == 2
    page.get_by_role("button", name=re.compile("Remove")).click()
    settle(page)
    assert len(download_yaml(page)["cohorts"]) == 1
    assert page.get_by_role("button", name=re.compile("Remove")).is_disabled()


def test_notes_banner_then_compilable_after_removal(page):
    # the example contains a `note` exclusion -> flagged not compilable,
    # and the banner names its position (Group A's note is exclusion 2)
    assert page.get_by_text("NOT deterministically compilable").is_visible()
    assert page.get_by_text(re.compile(r"› exclusion 2 \[note\]")).is_visible()
    # remove the note (the last ✕ inside the exclusions of group A)
    row = page.locator("[data-testid='stHorizontalBlock']").filter(
        has_text="Other criterion (no code yet)").last
    row.get_by_role("button", name="✕").click()
    settle(page)
    assert page.get_by_text("✓ ready").is_visible()
    assert page.get_by_text("deterministically compilable").is_visible()
    assert S.notes_in(download_yaml(page)) == []


def test_registry_warning_for_unknown_source(page, tmp_path):
    c = {"project": "p", "project_type": "recruitment", "target_n": "",
         "schema_version": S.SCHEMA_VERSION,
         "cohorts": [{"id": "g1", "name": "G", "exclusions": [], "inclusion": {
             "id": "c1", "op": "AND", "members": [
                 {"id": "l1", "kind": "codes", "label": "x",
                  "source": "mystery_db", "icd": ["A00"]}]}}]}
    f = tmp_path / "unknown_source.yaml"
    f.write_text(yaml.dump(c))
    page.get_by_text("Load a requirement.yaml").click()
    settle(page)
    page.locator("input[type='file']").set_input_files(str(f))
    settle(page)
    # passes the structural gate, but level-2 registry conformance warns
    assert page.get_by_text("passes the strict contract gate").is_visible()
    assert page.get_by_text("Registry conformance:").is_visible()
    assert page.get_by_text("not in the registry").is_visible()


def test_draft_coercions_reported_on_load(page, tmp_path):
    c = {"project": "p", "project_type": "recruitment",
         "schema_version": S.SCHEMA_VERSION,
         "cohorts": [{"id": "g1", "name": "G", "exclusions": [], "inclusion": {
             "id": "c1", "op": "AND", "members": [
                 {"id": "l1", "kind": "demographic", "sex": "both",
                  "age_min": 18}]}}]}
    f = tmp_path / "legacy_sex.yaml"
    f.write_text(yaml.dump(c))
    page.get_by_text("Load a requirement.yaml").click()
    settle(page)
    page.locator("input[type='file']").set_input_files(str(f))
    settle(page)
    assert page.get_by_text("does not pass the strict contract gate").is_visible()
    assert page.get_by_text("legacy sex 'both'").is_visible()   # coercion reported
    assert download_yaml(page)["cohorts"][0]["inclusion"]["members"][0].get("sex") is None


def test_contract_header_references_export(page):
    page.get_by_text("FINALIZE CONTRACT").click()
    settle(page)
    page.get_by_role("textbox", name="Extraction spec URI (optional)").fill(
        "https://example.org/extraction-spec")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("button", name=re.compile("Seal as agreed")).click()
    settle(page)
    got = download_yaml(page)
    assert got["contract"]["references"] == {
        "extraction_spec": "https://example.org/extraction-spec"}
    assert got["contract"]["status"] == "agreed"
    assert S.check_contract(got) == []


# ---------------------------------------------------------------------------
# Consecutive-interaction regressions: widgets bound via value=/index= without
# a stable key lose the SECOND change in a row (the rerun remounts the widget,
# and the next post goes to the dead widget id). All widgets now use stable
# keys — these tests do two changes back-to-back with nothing in between.
# ---------------------------------------------------------------------------
def sidebar(page):
    return page.locator("[data-testid='stSidebar']")


def test_consecutive_type_changes(page):
    sidebar(page).get_by_text("registry", exact=True).click()
    settle(page)
    sidebar(page).get_by_text("other", exact=True).click()
    settle(page)
    assert download_yaml(page)["project_type"] == "other"


def test_consecutive_group_switches(page):
    sidebar(page).get_by_text("Group B — controls").click()
    settle(page)
    sidebar(page).get_by_text("Group A — cases").click()
    settle(page)
    assert page.get_by_role("textbox", name="Group name").input_value() == "Group A — cases"


def test_consecutive_title_edits(page):
    t = page.get_by_role("textbox", name="Title")
    t.fill("first edit"); page.keyboard.press("Enter")
    settle(page)
    t = page.get_by_role("textbox", name="Title")
    t.fill("second edit"); page.keyboard.press("Enter")
    settle(page)
    assert download_yaml(page)["project"] == "second edit"


def test_consecutive_dialog_radio_changes(page):
    page.get_by_role("button", name="✎").nth(1).click()        # 'Adults'
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_text("female", exact=True).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_text("male", exact=True).click()                # consecutive!
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    leaf = download_yaml(page)["cohorts"][0]["inclusion"]["members"][0]
    assert leaf["sex"] == "male"


def test_dialog_state_resets_between_opens(page):
    # edit Adults -> change sex -> CANCEL; reopening must show the saved state,
    # not the abandoned edit (dlg_* keys are wiped on every open)
    page.get_by_role("button", name="✎").nth(1).click()
    settle(page)
    page.get_by_role("dialog").get_by_text("female", exact=True).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    settle(page)
    page.get_by_role("button", name="✎").nth(1).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    checked = dlg.locator("input[type=radio]:checked")
    # the Sex radio is the only radio group in the demographic dialog
    assert dlg.get_by_text("any", exact=True).count() == 1
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    leaf = download_yaml(page)["cohorts"][0]["inclusion"]["members"][0]
    assert leaf.get("sex") is None                              # 'any' is not exported


# ---------------------------------------------------------------------------
# Full clickable coverage — every remaining button/field has one behaviour test
# ---------------------------------------------------------------------------
def test_ticket_names_download(page):
    page.get_by_role("textbox", name="Ticket (optional)").fill("TICK-42")
    page.keyboard.press("Enter")
    settle(page)
    with page.expect_download() as di:
        page.get_by_role("button", name="Download YAML").click()
    assert di.value.suggested_filename == "TICK-42.requirement.yaml"
    assert yaml.safe_load(open(di.value.path()))["ticket"] == "TICK-42"


def test_contract_parties_export(page):
    page.get_by_text("FINALIZE CONTRACT").click()
    settle(page)
    page.get_by_role("textbox", name="Requested by").fill("Dr Who")
    page.keyboard.press("Enter")
    settle(page)
    page.get_by_role("textbox", name="Approved by").fill("A Reviewer")
    page.keyboard.press("Enter")
    settle(page)
    got = download_yaml(page)["contract"]
    assert got["requested_by"] == "Dr Who" and got["approved_by"] == "A Reviewer"


def test_remove_container_with_children(page):
    before = download_yaml(page)["cohorts"][0]["inclusion"]["members"]
    # ✕ order: Adults(0), OR 'Condition of interest'(1) — removes the subtree
    page.get_by_role("button", name="✕").nth(1).click()
    settle(page)
    after = download_yaml(page)["cohorts"][0]["inclusion"]["members"]
    assert len(after) == len(before) - 1
    assert not any(m.get("label") == "Condition of interest (any source)" for m in after)


def test_move_exclusion_up(page):
    before = download_yaml(page)["cohorts"][0]["exclusions"]
    page.get_by_role("button", name="↑").nth(1).click()    # second exclusion up
    settle(page)
    after = download_yaml(page)["cohorts"][0]["exclusions"]
    assert [e.get("label") for e in after[:2]] == [
        before[1].get("label"), before[0].get("label")]
    # ↑ on the FIRST exclusion is a no-op (already first)
    page.get_by_role("button", name="↑").first.click()
    settle(page)
    assert download_yaml(page)["cohorts"][0]["exclusions"] == after


def test_add_dialog_cancel(page):
    before = download_yaml(page)
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    settle(page)
    assert page.get_by_role("dialog").count() == 0
    assert download_yaml(page) == before


def test_container_dialog_cancel(page):
    before = download_yaml(page)
    page.get_by_role("button", name="✎").nth(2).click()    # OR container
    settle(page)
    page.get_by_role("dialog").get_by_text("INTERSECT — all of (AND)").click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    settle(page)
    assert download_yaml(page) == before                   # op change abandoned


def test_preview_dialog_download_and_close(page):
    page.get_by_role("button", name=re.compile("Preview YAML")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    with page.expect_download() as di:
        dlg.get_by_role("button", name=re.compile("Download")).click()
    from_preview = yaml.safe_load(open(di.value.path()))
    settle(page)
    # two 'Close' matches: ours + streamlit's dialog-chrome X — pick ours
    page.get_by_role("dialog").locator("[data-testid='stBaseButton-secondary']").filter(
        has_text="Close").click()
    settle(page)
    assert page.get_by_role("dialog").count() == 0
    # the preview's download equals the sidebar's download
    assert from_preview == download_yaml(page)


def test_demographic_all_fields(page):
    page.get_by_role("button", name="✎").nth(1).click()    # 'Adults'
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Age min").fill("20")
    dlg.get_by_role("textbox", name="Residence").fill("Region X")
    dlg.get_by_role("textbox", name="SIMD").fill("1-2")
    page.keyboard.press("Tab")
    settle(page)
    dlg = page.get_by_role("dialog")
    assert dlg.get_by_text("not yet compilable").is_visible()   # feasibility warning
    dlg.get_by_role("button", name="Save").click()
    settle(page)
    leaf = download_yaml(page)["cohorts"][0]["inclusion"]["members"][0]
    assert leaf["age_min"] == 20 and leaf["residence"] == "Region X" and leaf["simd"] == "1-2"


def test_note_condition_via_dialog(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = pick(page, page.get_by_role("dialog"), 0, "note")     # Kind -> note
    dlg.get_by_role("textbox", name="Text").fill("criterion with no agreed code")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    leaf = got["cohorts"][0]["inclusion"]["members"][-1]
    assert leaf["kind"] == "note" and leaf["text"] == "criterion with no agreed code"
    assert page.get_by_text("NOT deterministically compilable").is_visible()


def test_codes_prescribing_bnf_and_drug_names(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = pick(page, page.get_by_role("dialog"), 1, "prescribing")   # Source
    dlg.get_by_role("textbox", name="BNF").fill("0601")
    dlg.get_by_role("textbox", name="Drug names").fill("metformin")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    leaf = download_yaml(page)["cohorts"][0]["inclusion"]["members"][-1]
    assert leaf["source"] == "prescribing"
    assert leaf["bnf"] == ["0601"] and leaf["drug_names"] == ["metformin"]


def test_measure_op_change(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = pick(page, page.get_by_role("dialog"), 0, "measure")   # Kind
    dlg = pick(page, dlg, 3, "<")                                # Op (Kind,Source,Measure,Op)
    dlg.get_by_role("textbox", name="Value").fill("60")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    leaf = download_yaml(page)["cohorts"][0]["inclusion"]["members"][-1]
    assert leaf["op"] == "<" and leaf["value"] == 60


def test_anchor_occurrence_direction_unit(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="ICD-10").fill("E11")
    dlg.get_by_text("⏱ Timing (optional)").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_text("Anchor to a per-patient index event").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Event codes (one per line)").fill("X1")
    dlg.get_by_text("last occurrence", exact=True).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_text("after the index date", exact=True).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Within N (blank = any time)").fill("2")
    page.keyboard.press("Tab")
    settle(page)
    dlg = pick(page, page.get_by_role("dialog"), 4, "years")   # Unit select
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    anchor = download_yaml(page)["cohorts"][0]["inclusion"]["members"][-1]["when"]["anchor"]
    assert anchor["event"]["occurrence"] == "last"
    assert anchor["direction"] == "after"
    assert anchor["within"] == {"n": 2, "unit": "years"}


def test_seal_download_tamper_upload_cycle(page, tmp_path):
    # 1. seal the contract in the app
    page.get_by_text("FINALIZE CONTRACT").click()
    settle(page)
    page.get_by_role("button", name=re.compile("Seal as agreed")).click()
    settle(page)
    with page.expect_download() as di:
        page.get_by_role("button", name="Download YAML").click()
    sealed = yaml.safe_load(open(di.value.path()))
    assert sealed["contract"]["status"] == "agreed"

    # 2. upload the UNMODIFIED download -> passes the strict gate
    clean = tmp_path / "sealed.requirement.yaml"
    clean.write_bytes(open(di.value.path(), "rb").read())
    page.get_by_text("Load a requirement.yaml").click()
    settle(page)
    page.locator("input[type='file']").set_input_files(str(clean))
    settle(page)
    assert page.get_by_text("passes the strict contract gate").is_visible()

    # 3. tamper with the BODY offline (change one code), keep the header
    tampered = yaml.safe_load(open(di.value.path()))
    leaf = tampered["cohorts"][0]["inclusion"]["members"][1]["members"][0]
    leaf["icd"] = ["Z99"]                       # was A00
    bad = tmp_path / "tampered.requirement.yaml"
    bad.write_text(yaml.dump(tampered, sort_keys=False, allow_unicode=True))

    # 4. upload the tampered file -> gate rejects it, loudly
    page.locator("input[type='file']").set_input_files(str(bad))
    settle(page)
    assert page.get_by_text("does not pass the strict contract gate").is_visible()
    assert page.get_by_text("CHANGED since it was sealed").is_visible()

    # 5. re-sealing in the app re-approves the changed body (version bump).
    # The expander auto-opens when a header exists — only click it if closed.
    seal_btn = page.get_by_role("button", name=re.compile("Seal as agreed"))
    if not seal_btn.is_visible():
        page.get_by_text("FINALIZE CONTRACT").click()
        settle(page)
    seal_btn.click()
    settle(page)
    got = download_yaml(page)
    assert got["contract"]["version"] == sealed["contract"]["version"] + 1
    assert S.hash_status(got) == "ok"
    assert S.check_contract(got) == []
    assert got["cohorts"][0]["inclusion"]["members"][1]["members"][0]["icd"] == ["Z99"]


def test_edit_root_container_op(page):
    # the ROOT inclusion container is g['inclusion'] itself, not a member —
    # regression: replace_node used to miss it, silently dropping the edit
    page.get_by_role("button", name="✎").first.click()     # root INTERSECT
    settle(page)
    page.get_by_role("dialog").get_by_text("UNION — any of (OR)").click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    assert got["cohorts"][0]["inclusion"]["op"] == "OR"
    assert page.get_by_text("UNION").first.is_visible()     # badge updated too


def test_validation_message_and_ordinal_chips(page):
    # adding an empty UNION exclusion: the error names its position, and the
    # cards carry matching ordinal chips (1, 2, 2.1 …)
    page.get_by_role("button", name=re.compile(r"Add exclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("UNION")).click()
    settle(page)
    assert page.get_by_text(re.compile(r"› exclusion 3: this UNION")).is_visible()
    assert page.locator(".ord", has_text=re.compile(r"^2\.1$")).count() == 1  # nested chip
    assert page.locator(".ord", has_text=re.compile(r"^3$")).count() >= 1    # the new exclusion


def test_code_form_warning_in_dialog(page):
    # hospital_admissions offers both ICD-10 and OPCS-4; entering a code
    # deeper than the allowed depth warns immediately in the dialog
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    assert dlg.get_by_role("textbox", name="OPCS-4").count() == 1
    dlg.get_by_role("textbox", name="ICD-10").fill("F02.31")
    page.keyboard.press("Tab")
    settle(page)
    dlg = page.get_by_role("dialog")
    assert dlg.get_by_text(re.compile("invalid ICD-10: F02.31")).is_visible()
    dlg.get_by_role("textbox", name="ICD-10").fill("F02.3")
    dlg.get_by_role("textbox", name="OPCS-4").fill("L29")
    page.keyboard.press("Tab")
    settle(page)
    dlg = page.get_by_role("dialog")
    assert dlg.get_by_text(re.compile("invalid ICD-10")).count() == 0
    dlg.get_by_role("button", name="Save").click()
    settle(page)
    leaf = download_yaml(page)["cohorts"][0]["inclusion"]["members"][-1]
    assert leaf["icd"] == ["F02.3"] and leaf["opcs"] == ["L29"]


def test_anchor_code_form_warning(page):
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="ICD-10").fill("E11")
    dlg.get_by_text("⏱ Timing (optional)").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_text("Anchor to a per-patient index event").click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Event codes (one per line)").fill("X1")
    page.keyboard.press("Tab")
    settle(page)
    dlg = page.get_by_role("dialog")
    assert dlg.get_by_text(re.compile("invalid ICD-10: X1")).is_visible()
    dlg.get_by_role("textbox", name="Event codes (one per line)").fill("E10")
    page.keyboard.press("Tab")
    settle(page)
    assert page.get_by_role("dialog").get_by_text(re.compile("invalid ICD-10")).count() == 0
