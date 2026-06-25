"""Cohort Requirement Builder — Streamlit form.

Researcher authors a SHARE/GoSHARE cohort requirement directly; the app emits a
`requirement.yaml` (the contract for the cohort builder). Structure mirrors the
RDMP CIC: each group = one build; inclusion CONTAINER (AND=INTERSECT / OR=UNION)
built first, then an ORDERED list of exclusions subtracted in turn (root EXCEPT).

See docs/SPEC.md. Schema lives in requirement_schema.py (single source of truth).
"""
import copy

import yaml
import streamlit as st

import requirement_schema as S

st.set_page_config(page_title="Cohort Requirement Builder", layout="wide")
NBSP = "&nbsp;&nbsp;&nbsp;&nbsp;"

CSS = """
<style>
/* higher-contrast body text */
.stApp, .stMarkdown p, .stMarkdown span, label, .stRadio, .stTextInput { color: #14161c; }
/* thicker, higher-contrast bordered containers */
div[data-testid="stVerticalBlockBorderWrapper"] {
  border: 3px solid #3a3f4b !important;
  border-radius: 10px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
/* high-contrast inline code tags  ([codes], [sample] …) */
.stMarkdown code {
  background: #e6e9f0 !important;
  color: #1a1c24 !important;
  border: 1px solid #c7ccd8;
  padding: 1px 6px; border-radius: 5px; font-weight: 600;
}
/* darker captions (were low-contrast grey) */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #44485a !important; }
/* big, bold group-name field */
input[aria-label="Group name"] {
  font-size: 1.5rem !important; font-weight: 700 !important; color: #14161c !important;
  padding: 0.5rem 0.7rem !important;
}
/* soft card fill so white rows sit on an off-white box (clearer boundaries) */
div[data-testid="stVerticalBlockBorderWrapper"] { background: #fafbfd; }
/* coloured section headers: keep (green) vs remove (red) */
.sec-head { font-size: 1.15rem; font-weight: 700; padding: 8px 12px;
            border-radius: 6px; margin-bottom: 12px; }
.sec-inc { background: #e6f4ea; color: #0f5132; border-left: 7px solid #2e8b57; }
.sec-exc { background: #fdeaea; color: #842029; border-left: 7px solid #c0392b; }
/* dialog: clear border + readable, bordered fields */
div[role="dialog"] { border: 2px solid #3a3f4b !important; border-radius: 12px !important;
                     box-shadow: 0 8px 30px rgba(0,0,0,0.25) !important; }
div[role="dialog"] input, div[role="dialog"] textarea {
  border: 1px solid #8b91a3 !important; background: #ffffff !important; color: #14161c !important; }
div[role="dialog"] label, div[role="dialog"] p, div[role="dialog"] span { color: #14161c !important; }
</style>
"""


# ----------------------------- state helpers -------------------------------
def init():
    if "req" not in st.session_state:
        st.session_state.req = S.build_example()   # start populated; "New" clears it
    if "sel" not in st.session_state:
        st.session_state.sel = 0
    st.session_state.setdefault("modal", None)
    st.session_state.setdefault("work", None)


def group():
    req = st.session_state.req
    st.session_state.sel = min(st.session_state.sel, len(req["cohorts"]) - 1)
    return req["cohorts"][st.session_state.sel]


def _find(lst, _id):
    for i, n in enumerate(lst):
        if n["_id"] == _id:
            return lst, i
        if n.get("node") == "container":
            hit = _find(n["members"], _id)
            if hit:
                return hit
    return None


def find_node(g, _id):
    if g["inclusion"]["_id"] == _id:
        return g["inclusion"]
    hit = _find(g["inclusion"]["members"], _id) or _find(g["exclusions"], _id)
    return hit[0][hit[1]] if hit else None


def remove_node(g, _id):
    hit = _find(g["inclusion"]["members"], _id) or _find(g["exclusions"], _id)
    if hit:
        hit[0].pop(hit[1])


def replace_node(g, _id, new):
    hit = _find(g["inclusion"]["members"], _id) or _find(g["exclusions"], _id)
    if hit:
        hit[0][hit[1]] = new


def open_modal(mode, work, **extra):
    st.session_state.modal = {"mode": mode, **extra}
    st.session_state.work = copy.deepcopy(work)
    st.rerun()


def close_modal():
    st.session_state.modal = None
    st.session_state.work = None


# ----------------------------- small parsers -------------------------------
def _int(s):
    s = (s or "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def _s(v):
    return "" if v is None else str(v)


def _lines(txt):
    return [ln.strip() for ln in (txt or "").splitlines() if ln.strip()]


def _join(lst):
    return "\n".join(lst or [])


# ----------------------------- summaries -----------------------------------
def summary(n):
    if n.get("node") == "container":
        return f"**{n['op']}**" + (f" · {n['label']}" if n.get("label") else " group")
    k = n["kind"]
    lbl = n.get("label") or k
    if k == "codes":
        vocs = [f"{f.upper().replace('_', ' ')} {', '.join(n[f])}"
                for f in ("icd", "read", "bnf", "drug_names") if n.get(f)]
        return f"`[codes]` {lbl} — {n.get('source', '?')} · " + " · ".join(vocs)
    if k == "demographic":
        bits = []
        if n.get("age_min") is not None or n.get("age_max") is not None:
            bits.append(f"age {_s(n.get('age_min'))}–{_s(n.get('age_max'))}")
        if n.get("residence"):
            bits.append(n["residence"])
        if n.get("simd"):
            bits.append(f"SIMD {n['simd']}")
        return f"`[demographic]` {lbl}" + (f" — {', '.join(bits)}" if bits else "")
    if k == "sample":
        se = n["sample_event"]
        ev = se["event"]
        w = f" within {se['within']}" if se.get("within") else ""
        return (f"`[sample]` {lbl} — ≥1 sample {se['direction']} "
                f"{ev['occurrence']} {ev['type']} index{w}")
    return f"`[note]` {lbl}"


# ----------------------------- tree rendering ------------------------------
GUIDE = "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#9aa0b3;white-space:pre"


def _g(s):
    return f"<span style='{GUIDE}'>{s}</span>" if s else ""


def render_member(g, n, guide, is_last, is_excl, sib, idx, is_root=False, top=False):
    if is_root:
        branch, child = "", ""
    else:
        branch = guide + ("└── " if is_last else "├── ")
        child = guide + ("     " if is_last else "│    ")
    cols = st.columns([8, 0.7, 0.7, 0.7, 0.7])
    cols[0].markdown(_g(branch) + summary(n), unsafe_allow_html=True)
    if cols[1].button("✎", key=f"e{n['_id']}", help="edit"):
        open_modal("edit_container" if n.get("node") == "container" else "edit_leaf", n, id=n["_id"])
    if not is_root and cols[2].button("✕", key=f"x{n['_id']}", help="remove"):
        remove_node(g, n["_id"]); st.rerun()
    if is_excl and top:
        if cols[3].button("↑", key=f"u{n['_id']}") and idx > 0:
            sib[idx - 1], sib[idx] = sib[idx], sib[idx - 1]; st.rerun()
        if cols[4].button("↓", key=f"d{n['_id']}") and idx < len(sib) - 1:
            sib[idx + 1], sib[idx] = sib[idx], sib[idx + 1]; st.rerun()

    if n.get("node") == "container":
        m = n["members"]
        for j, ch in enumerate(m):
            render_member(g, ch, child, j == len(m) - 1, is_excl, m, j)
        a = st.columns([1.6, 2.1, 2.4, 3.9])
        a[0].markdown(_g(child + "╰╴"), unsafe_allow_html=True)
        if a[1].button("➕ condition", key=f"ac{n['_id']}"):
            open_modal("add_leaf", S.new_codes(), container=n["_id"])
        if a[2].button("➕ AND/OR group", key=f"ag{n['_id']}"):
            n["members"].append(S.new_container("AND")); st.rerun()


# ----------------------------- dialogs -------------------------------------
@st.dialog("Condition")
def leaf_dialog():
    work = st.session_state.work
    nk = st.selectbox("Kind", S.KINDS, index=S.KINDS.index(work["kind"]))
    if nk != work["kind"]:
        nid = work["_id"]
        work = S.new_leaf(nk, work.get("label", ""))
        work["_id"] = nid
        st.session_state.work = work
    work["label"] = st.text_input("Label", work.get("label", ""))
    k = work["kind"]

    if k == "demographic":
        work["source"] = st.text_input("Source / catalogue", work.get("source", "SHARE_Demography"))
        c = st.columns(2)
        work["age_min"] = _int(c[0].text_input("Age min", _s(work.get("age_min"))))
        work["age_max"] = _int(c[1].text_input("Age max", _s(work.get("age_max"))))
        work["sex"] = st.text_input("Sex", work.get("sex", "both"))
        work["residence"] = st.text_input("Residence", work.get("residence", ""))
        work["simd"] = st.text_input("SIMD", work.get("simd", ""))
    elif k == "codes":
        work["source"] = st.text_input("Source / catalogue", work.get("source", ""),
                                       placeholder="e.g. SMR01, GP, PIS")
        c = st.columns(2)
        work["icd"] = _lines(c[0].text_area("ICD-10", _join(work.get("icd")), height=90))
        work["read"] = _lines(c[1].text_area("READ", _join(work.get("read")), height=90))
        c2 = st.columns(2)
        work["bnf"] = _lines(c2[0].text_area("BNF", _join(work.get("bnf")), height=90))
        work["drug_names"] = _lines(c2[1].text_area("Drug names", _join(work.get("drug_names")), height=90))
        st.caption("one code/range per line · e.g. E11, F00-09, C00-D48, 6.1-6.6")
    elif k == "sample":
        st.caption("ⓘ Counts PEOPLE who have ≥1 sample positioned vs the event. The sample is not selected.")
        se = work["sample_event"]
        ev = se["event"]
        ev["type"] = st.selectbox("Event type", S.EVENT_TYPES, index=S.EVENT_TYPES.index(ev["type"]))
        st.caption(f"codes vocabulary for this event: **{S.EVENT_VOCAB[ev['type']]}**")
        ev["occurrence"] = st.radio("Occurrence (defines the index date)", S.OCCURRENCE,
                                    index=S.OCCURRENCE.index(ev["occurrence"]), horizontal=True)
        ev["label"] = st.text_input("Event label", ev.get("label", ""))
        ev["codes"] = _lines(st.text_area("Event codes (one per line)", _join(ev.get("codes")), height=80))
        se["direction"] = st.radio("Sample is", S.DIRECTION,
                                   index=S.DIRECTION.index(se["direction"]), horizontal=True)
        se["within"] = st.text_input("Within window (blank = any time in that direction)",
                                     se.get("within", ""), placeholder="e.g. 6 months")
    elif k == "note":
        work["text"] = st.text_area("Text", work.get("text", ""), height=90)

    b = st.columns(2)
    if b[0].button("Save", type="primary", use_container_width=True):
        g = group()
        m = st.session_state.modal
        if m["mode"] == "edit_leaf":
            replace_node(g, work["_id"], work)
        elif m["container"] == "__EXCL__":
            g["exclusions"].append(work)
        else:
            find_node(g, m["container"])["members"].append(work)
        close_modal(); st.rerun()
    if b[1].button("Cancel", use_container_width=True):
        close_modal(); st.rerun()


@st.dialog("Group (container)")
def container_dialog():
    work = st.session_state.work
    work["op"] = st.radio("Operator", S.OPS, index=S.OPS.index(work["op"]),
                          horizontal=True, help="AND = INTERSECT · OR = UNION")
    work["label"] = st.text_input("Label (optional)", work.get("label", ""))
    b = st.columns(2)
    if b[0].button("Save", type="primary", use_container_width=True):
        replace_node(group(), work["_id"], work); close_modal(); st.rerun()
    if b[1].button("Cancel", use_container_width=True):
        close_modal(); st.rerun()


# ----------------------------- sidebar -------------------------------------
def sidebar():
    req = st.session_state.req
    with st.sidebar:
        st.title("Cohort Requirement Builder")
        st.subheader("Project")
        req["project"] = st.text_input("Title", req["project"])
        req["project_type"] = st.radio("Type", S.PROJECT_TYPES,
                                       index=S.PROJECT_TYPES.index(req["project_type"]), horizontal=True)
        req["target_n"] = st.text_input("Target N", req["target_n"])
        req["ticket"] = st.text_input("Ticket (optional)", req.get("ticket", ""))

        st.divider()
        st.subheader("Groups")
        st.caption("each group = one complete RDMP build")
        names = [g["name"] or f"Group {i+1}" for i, g in enumerate(req["cohorts"])]
        st.session_state.sel = st.radio("group", range(len(names)),
                                        format_func=lambda i: names[i],
                                        index=min(st.session_state.sel, len(names) - 1),
                                        label_visibility="collapsed")
        c = st.columns(3)
        if c[0].button("➕ Add", use_container_width=True, help="add a new empty group"):
            req["cohorts"].append(S.new_group(f"Group {len(req['cohorts'])+1}"))
            st.session_state.sel = len(req["cohorts"]) - 1; st.rerun()
        if c[1].button("⧉ Clone", use_container_width=True,
                       help="duplicate this group as a starting point for a similar cohort"):
            clone = S.clone_group(req["cohorts"][st.session_state.sel])
            req["cohorts"].insert(st.session_state.sel + 1, clone)
            st.session_state.sel += 1; st.rerun()
        if c[2].button("🗑 Remove", use_container_width=True, disabled=len(req["cohorts"]) <= 1):
            req["cohorts"].pop(st.session_state.sel)
            st.session_state.sel = 0; st.rerun()

        st.divider()
        st.subheader("Output")
        contract = S.to_contract(req)
        text = yaml.dump(contract, sort_keys=False, allow_unicode=True)
        fname = (req.get("ticket") or req.get("project") or "requirement").split()[0]
        st.download_button("⬇ Download YAML", text, f"{fname}.requirement.yaml",
                           "text/yaml", use_container_width=True, type="primary")
        with st.expander("YAML preview", expanded=False):
            st.code(text, language="yaml")
        if st.button("New (blank requirement)", use_container_width=True):
            st.session_state.req = S.new_requirement()
            st.session_state.sel = 0; st.rerun()


# ----------------------------- main ----------------------------------------
def main():
    init()
    st.markdown(CSS, unsafe_allow_html=True)
    sidebar()
    req = st.session_state.req
    g = group()

    st.markdown("### Group name")
    g["name"] = st.text_input("Group name", g["name"], label_visibility="collapsed")
    st.caption("ⓘ This group defines one complete RDMP build "
               "(inclusion container, then exclusions subtracted in order).")

    with st.container(border=True):
        st.markdown("<div class='sec-head sec-inc'>INCLUSION — base population (keep)</div>",
                    unsafe_allow_html=True)
        render_member(g, g["inclusion"], "", True, False, None, None, is_root=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("<div class='sec-head sec-exc'>EXCLUSIONS — removed from the population, in order ↓</div>",
                    unsafe_allow_html=True)
        n_ex = len(g["exclusions"])
        for i, m in enumerate(g["exclusions"]):
            render_member(g, m, "", i == n_ex - 1, True, g["exclusions"], i, top=True)
        a = st.columns([2.2, 2.5, 6])
        if a[0].button("➕ Add exclusion"):
            open_modal("add_leaf", S.new_codes(), container="__EXCL__")
        if a[1].button("➕ Add exclusion group"):
            g["exclusions"].append(S.new_container("OR")); st.rerun()

    errs = S.validate(req)
    if errs:
        st.error("Not ready:\n\n" + "\n".join(f"- {e}" for e in errs))
    else:
        st.success(f"✓ ready — {len(req['cohorts'])} group(s), each a valid build")

    if st.session_state.modal:
        mode = st.session_state.modal["mode"]
        (container_dialog if mode == "edit_container" else leaf_dialog)()


main()
