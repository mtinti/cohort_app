"""Health Cohort Builder — Streamlit form.

A researcher authors a cohort definition directly; the app emits a
`requirement.yaml`. Each cohort group is self-contained: an inclusion CONTAINER
(items combined with AND=INTERSECT / OR=UNION; may nest), then an ORDERED list of
exclusions removed in turn.

See docs/SPEC.md. Schema lives in requirement_schema.py (single source of truth).
"""
import copy

import yaml
import streamlit as st

import registry as R
import requirement_schema as S

st.set_page_config(page_title="Health Cohort Builder", layout="wide")
NBSP = "&nbsp;&nbsp;&nbsp;&nbsp;"
# Display names for the set operators (stored op stays AND/OR in the YAML contract)
OP_LABEL = {"AND": "INTERSECT", "OR": "UNION"}
OP_MEAN = {"AND": "all of · AND", "OR": "any of · OR"}
OP_FULL = {"AND": "INTERSECT — all of (AND)", "OR": "UNION — any of (OR)"}

CSS = """
<style>
/* higher-contrast body text */
.stApp, .stMarkdown p, .stMarkdown span, label, .stRadio, .stTextInput { color: #14161c; }
/* anchor links (#group-name …) must not scroll the heading under the fixed header */
h1, h2, h3, h4 { scroll-margin-top: 4.5rem; }
/* high-contrast inline code tags  ([codes], [demographic] …) */
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
/* colour-blind-safe section headers (Okabe-Ito blue vs orange) + icon + text */
.sec-head { font-size: 1.15rem; font-weight: 700; padding: 8px 12px;
            border-radius: 6px; margin-bottom: 12px; }
.sec-inc { background: #dce9f5; color: #0b3d66; border-left: 7px solid #0072B2; }
.sec-exc { background: #fbe7d2; color: #6e3500; border-left: 7px solid #D55E00; }
/* card headers: op badge for containers (blue AND vs green OR), bold leaf title */
.op-badge { display: inline-block; font-weight: 700; padding: 2px 10px;
            border-radius: 6px; font-size: 0.95em; }
.op-and { background: #dce9f5; color: #0b3d66; border: 1px solid #0072B2; }
.op-or  { background: #d9f2e8; color: #0b4d3d; border: 1px solid #009E73; }
.leaf-head { font-weight: 650; }
/* ordinal chip: the card's position (2.1 = child 1 of item 2) — validation
   messages reference exactly these numbers */
.ord { font-family: monospace; font-size: 0.82em; color: #44485a;
       background: #eef1f6; border: 1px solid #c7ccd8; border-radius: 4px;
       padding: 1px 7px; margin-right: 7px; }
.leaf-body { color: #3a3f4b; font-size: 0.92em; margin: 0 0 2px 2px; line-height: 1.55; }
/* NOTE: streamlit >= 1.58 has no stVerticalBlockBorderWrapper — bordered
   containers are stLayoutWrapper > stVerticalBlock. Card-header rows are
   identified by OUR classes (.op-badge / .leaf-head in the first column), so
   these rules touch nothing else (not dialogs, not the sidebar).
   The title column flexes; the ACTION columns keep a FIXED width at every
   viewport size, so the ➕ ✎ ✕ glyphs stay centred in their buttons instead
   of shrinking off-centre on narrow pages. */
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .op-badge),
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .leaf-head) {
  align-items: center !important; flex-wrap: nowrap !important; gap: 0.45rem !important; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .op-badge) > div[data-testid="stColumn"]:first-child,
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .leaf-head) > div[data-testid="stColumn"]:first-child {
  flex: 1 1 auto !important; min-width: 0 !important; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .op-badge) > div[data-testid="stColumn"]:not(:first-child),
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .leaf-head) > div[data-testid="stColumn"]:not(:first-child) {
  flex: 0 0 2.6rem !important; width: 2.6rem !important; min-width: 2.6rem !important; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .op-badge) > div[data-testid="stColumn"]:not(:first-child) :is([data-testid="stElementContainer"], [class*="stButton"]),
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .leaf-head) > div[data-testid="stColumn"]:not(:first-child) :is([data-testid="stElementContainer"], [class*="stButton"]) {
  width: 100% !important; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .op-badge) button,
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:first-child .leaf-head) button {
  width: 100% !important; min-height: 2.2rem !important; padding: 0.15rem 0 !important;
  display: inline-flex; align-items: center; justify-content: center; }
/* tighter vertical rhythm inside cards (header row ~touching its body) */
div[data-testid="stLayoutWrapper"] > div[data-testid="stVerticalBlock"] { gap: 0.4rem !important; }
/* dialog: clear border + readable, bordered fields */
div[role="dialog"] { border: 2px solid #3a3f4b !important; border-radius: 12px !important;
                     box-shadow: 0 8px 30px rgba(0,0,0,0.25) !important; }
div[role="dialog"] input, div[role="dialog"] textarea {
  border: 1px solid #8b91a3 !important; background: #ffffff !important; color: #14161c !important; }
/* …but NOT the selectbox's internal 4px search input: bordering it draws a
   tiny square with a blinking caret right after the selected value */
div[role="dialog"] [data-baseweb="select"] input {
  border: none !important; background: transparent !important;
  caret-color: transparent !important; }
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
    st.session_state.setdefault("load_report", None)
    # deferred widget-state syncs (widget keys may only be written BEFORE the
    # widget is instantiated, so handlers queue them and init applies them)
    if st.session_state.pop("_wipe_w", False):          # after Load / New
        for k in [k for k in st.session_state if k.startswith("w_")]:
            del st.session_state[k]
    if "_pend_group" in st.session_state:               # after Add/Clone/Remove group
        st.session_state["w_group"] = st.session_state.pop("_pend_group")


# ----------------------------- keyed widgets --------------------------------
# Every widget that displays app state uses a STABLE key and gets its value
# from session state. Binding via `value=`/`index=` without a key makes the
# widget's identity depend on the shown value, so the rerun after an edit
# remounts it — and the NEXT consecutive interaction posts to the dead widget
# and is silently dropped ("first click fails, second succeeds").
def _init_choice(key, options, current):
    if key not in st.session_state or st.session_state[key] not in options:
        st.session_state[key] = current if current in options else options[0]


def kselect(label, options, current, key, **kw):
    options = list(options)
    _init_choice(key, options, current)
    return st.selectbox(label, options, key=key, **kw)


def kradio(label, options, current, key, **kw):
    options = list(options)
    _init_choice(key, options, current)
    return st.radio(label, options, key=key, **kw)


def ktext(label, value, key, **kw):
    if key not in st.session_state:
        st.session_state[key] = "" if value is None else str(value)
    return st.text_input(label, key=key, **kw)


def karea(label, value, key, **kw):
    if key not in st.session_state:
        st.session_state[key] = value or ""
    return st.text_area(label, key=key, **kw)


def kcheck(label, value, key, **kw):
    if key not in st.session_state:
        st.session_state[key] = bool(value)
    return st.checkbox(label, key=key, **kw)


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
    if g["inclusion"]["_id"] == _id:      # the ROOT container is not a member
        g["inclusion"] = new
        return
    hit = _find(g["inclusion"]["members"], _id) or _find(g["exclusions"], _id)
    if hit:
        hit[0][hit[1]] = new


def open_modal(mode, work, **extra):
    st.session_state.modal = {"mode": mode, **extra}
    st.session_state.work = copy.deepcopy(work)
    for k in [k for k in st.session_state if k.startswith("dlg_")]:
        del st.session_state[k]        # dialog widgets re-init from the fresh work copy
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


# ----------------------------- summaries (HTML) ----------------------------
def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _when_lines(n):
    w = n.get("when") or {}
    out = []
    win = w.get("window") or {}
    if win.get("from") or win.get("to"):
        out.append(f"⏱ window {_esc(win.get('from', '…'))} → {_esc(win.get('to', '…'))}")
    a = w.get("anchor")
    if a:
        wi = a.get("within") or {}
        within = f" within {wi['n']} {_esc(wi.get('unit', ''))}" if wi.get("n") else ""
        ev = a.get("event", {})
        out.append(f"⏱ {a.get('direction', '?')} the {ev.get('occurrence', 'first')} "
                   f"<b>{_esc(ev.get('source', '?'))}</b> event "
                   f"({_esc(', '.join(ev.get('codes', [])))}){within}")
    return out


def header_html(n):
    """Card header: op badge for containers, kind chip + label for leaves."""
    if n.get("node") == "container":
        op = n["op"]
        cls = "op-and" if op == "AND" else "op-or"
        head = (f"<span class='op-badge {cls}'>{OP_LABEL[op]}</span> "
                f"<span style='color:#5b6270;font-size:0.88em'>{OP_MEAN[op]}</span>")
        return head + (f" · <b>{_esc(n['label'])}</b>" if n.get("label") else "")
    k = n["kind"]
    return f"<code>[{k}]</code> <span class='leaf-head'>{_esc(n.get('label') or k)}</span>"


def body_html(n):
    """Card body: the leaf's details, one line per aspect."""
    k = n["kind"]
    lines = []
    if k == "codes":
        lines.append(f"source: <b>{_esc(n.get('source', '?'))}</b>")
        for f, lab in (("icd", "ICD-10"), ("opcs", "OPCS-4"), ("read", "READ"),
                       ("bnf", "BNF"), ("drug_names", "Drug names")):
            if n.get(f):
                lines.append(f"{lab}: {_esc(', '.join(n[f]))}")
        lines += _when_lines(n)
    elif k == "measure":
        lines.append(f"source: <b>{_esc(n.get('source', '?'))}</b> · "
                     f"{_esc(n.get('measure', '?'))} {_esc(n.get('op', '?'))} "
                     f"{_s(n.get('value'))} {_esc(n.get('unit', ''))}")
        lines += _when_lines(n)
    elif k == "demographic":
        bits = []
        if n.get("age_min") is not None or n.get("age_max") is not None:
            bits.append(f"age {_s(n.get('age_min'))}–{_s(n.get('age_max'))}")
        if n.get("sex") and n["sex"] != "any":
            bits.append(_esc(n["sex"]))
        if n.get("residence"):
            bits.append(_esc(n["residence"]))
        if n.get("simd"):
            bits.append(f"SIMD {_esc(n['simd'])}")
        if bits:
            lines.append(" · ".join(bits))
    elif k == "sample":
        se = n["sample_event"]
        ev = se["event"]
        wi = se.get("within") or {}
        w = f" within {wi['n']} {_esc(wi.get('unit', ''))}" if wi.get("n") else ""
        lines.append(f"≥1 sample {se['direction']} the {ev['occurrence']} "
                     f"<b>{_esc(ev['type'])}</b> event "
                     f"({_esc(', '.join(ev.get('codes', [])))}){w}")
    elif k == "note":
        lines.append(f"<i>{_esc(n.get('text', ''))}</i>")
    return "<br>".join(lines)


# ----------------------------- tree rendering ------------------------------
# Every node is a CARD (bordered container): header row = badge/chip + label +
# actions; body = the details (leaves) or the nested member cards (containers).
# Nesting shows through containment, so no connector rails are needed.
def render_member(g, n, is_excl=False, sib=None, idx=None, is_root=False, top=False,
                  path=""):
    is_c = n.get("node") == "container"
    with st.container(border=True):
        # exactly the needed action columns, so buttons pack flush to the
        # card's right edge on every row (no phantom empty slots)
        n_btn = (1 if is_c else 0) + 1 + (0 if is_root else 1) + (2 if (is_excl and top) else 0)
        cols = st.columns([10 - 0.62 * n_btn] + [0.62] * n_btn)
        ord_chip = f"<span class='ord'>{path}</span>" if path else ""
        cols[0].markdown(ord_chip + header_html(n), unsafe_allow_html=True)
        i = 1
        # ➕ lives on the CONTAINER's own header, so it is unambiguous which
        # container you add into
        if is_c:
            if cols[i].button("➕", key=f"a{n['_id']}",
                              help="add a condition or sub-container into THIS container"):
                open_modal("add_to", {}, container=n["_id"])
            i += 1
        if cols[i].button("✎", key=f"e{n['_id']}", help="edit"):
            open_modal("edit_container" if is_c else "edit_leaf", n, id=n["_id"])
        i += 1
        if not is_root:
            if cols[i].button("✕", key=f"x{n['_id']}", help="remove"):
                remove_node(g, n["_id"]); st.rerun()
            i += 1
        if is_excl and top:
            if cols[i].button("↑", key=f"u{n['_id']}", help="subtract earlier") and idx > 0:
                sib[idx - 1], sib[idx] = sib[idx], sib[idx - 1]; st.rerun()
            if cols[i + 1].button("↓", key=f"d{n['_id']}", help="subtract later") and idx < len(sib) - 1:
                sib[idx + 1], sib[idx] = sib[idx], sib[idx + 1]; st.rerun()

        if is_c:
            if not n["members"]:       # visible placeholder so an empty container isn't invisible
                st.caption(f"empty {OP_LABEL[n['op']]} container ({OP_MEAN[n['op']]}) "
                           "— use ➕ in the header above to add")
            for j, ch in enumerate(n["members"]):
                child_path = f"{path}.{j + 1}" if path else str(j + 1)
                render_member(g, ch, is_excl, n["members"], j, path=child_path)
        else:
            body = body_html(n)
            if body:
                st.markdown(f"<div class='leaf-body'>{body}</div>", unsafe_allow_html=True)


# ----------------------------- dialogs -------------------------------------
def _source_select(work, kind, label="Source (logical, from the registry)"):
    opts = R.sources_for(kind)
    cur = work.get("source", "")
    if cur and cur not in opts:          # loaded value the registry doesn't know
        opts = [cur] + opts
        st.warning(f"source '{cur}' is not in the registry — pick a logical source")
    work["source"] = kselect(label, opts, cur, key="dlg_src")
    desc = R.SOURCES.get(work["source"], {}).get("description")
    if desc:
        st.caption(desc)


def _timing_editor(work):
    w = work.get("when") or {}
    with st.expander("⏱ Timing (optional)", expanded=bool(w.get("window") or w.get("anchor"))):
        win = dict(w.get("window") or {})
        c = st.columns(2)
        with c[0]:
            f = ktext("Window from (YYYY-MM-DD)", win.get("from", ""), key="dlg_w_from")
        with c[1]:
            t = ktext("Window to (YYYY-MM-DD)", win.get("to", ""), key="dlg_w_to")
        window = {}
        if f.strip():
            window["from"] = f.strip()
        if t.strip():
            window["to"] = t.strip()
        anchor = None
        if kcheck("Anchor to a per-patient index event", bool(w.get("anchor")),
                  key="dlg_a_on"):
            a = w.get("anchor") or {}
            ev = a.get("event") or {}
            src = kselect("Index event source", R.sources_for("anchor"),
                          ev.get("source"), key="dlg_a_src")
            vocab = kselect("Event vocabulary", R.vocabs_for(src) or [""],
                            ev.get("vocab"), key="dlg_a_vocab")
            occ = kradio("Index date is the", S.OCCURRENCE, ev.get("occurrence", "first"),
                         key="dlg_a_occ", horizontal=True,
                         format_func=lambda o: f"{o} occurrence")
            codes = _lines(karea("Event codes (one per line)", _join(ev.get("codes")),
                                 key="dlg_a_codes", height=70))
            direction = kradio("This condition happens", S.DIRECTION,
                               a.get("direction", "before"), key="dlg_a_dir",
                               horizontal=True, format_func=lambda d: f"{d} the index date")
            wi = a.get("within") or {}
            cw = st.columns(2)
            with cw[0]:
                n = _int(ktext("Within N (blank = any time)", _s(wi.get("n")), key="dlg_a_n"))
            with cw[1]:
                unit = kselect("Unit", S.WITHIN_UNITS, wi.get("unit", "months"),
                               key="dlg_a_unit")
            anchor = {"event": {"source": src, "vocab": vocab, "codes": codes,
                                "occurrence": occ, "label": ev.get("label", "")},
                      "direction": direction, "within": {"n": n, "unit": unit}}
        work["when"] = {"window": window, "anchor": anchor} if (window or anchor) else None


@st.dialog("Condition")
def leaf_dialog():
    work = st.session_state.work
    # offer the flag-gated UI kinds; a loaded contract may carry a kind the UI
    # doesn't offer for new conditions — keep it selectable so it stays editable
    kinds = list(S.UI_KINDS) if work["kind"] in S.UI_KINDS else [work["kind"]] + list(S.UI_KINDS)
    nk = kselect("Kind", kinds, work["kind"], key="dlg_kind")
    if nk != work["kind"]:
        nid = work["_id"]
        work = S.new_leaf(nk, work.get("label", ""))
        work["_id"] = nid
        st.session_state.work = work
    work["label"] = ktext("Label", work.get("label", ""), key="dlg_label")
    k = work["kind"]

    if k == "demographic":
        _source_select(work, "demographic")
        c = st.columns(2)
        with c[0]:
            work["age_min"] = _int(ktext("Age min", _s(work.get("age_min")), key="dlg_agemin"))
        with c[1]:
            work["age_max"] = _int(ktext("Age max", _s(work.get("age_max")), key="dlg_agemax"))
        sex = work.get("sex") if work.get("sex") in S.SEXES else "any"
        work["sex"] = kradio("Sex", S.SEXES, sex, key="dlg_sex", horizontal=True)
        work["residence"] = ktext("Residence", work.get("residence", ""), key="dlg_res")
        work["simd"] = ktext("SIMD", work.get("simd", ""), key="dlg_simd")
        if work.get("residence") or work.get("simd"):
            st.caption("⚠ residence/SIMD are free text — recorded in the contract but "
                       "not yet compilable (they will fail site feasibility)")
    elif k == "codes":
        _source_select(work, "codes")
        legal = R.vocabs_for(work["source"])
        labels = {"icd": "ICD-10", "opcs": "OPCS-4", "read": "READ", "bnf": "BNF",
                  "drug_names": "Drug names"}
        # only the vocabularies the registry allows for this source are editable
        shown = [f for f, v in R.VOCAB_FIELDS.items() if v in legal]
        cols = st.columns(2) if len(shown) > 1 else [st.container()]
        for i, f in enumerate(shown):
            with cols[i % len(cols)]:
                work[f] = _lines(karea(labels[f], _join(work.get(f)),
                                       key=f"dlg_codes_{f}", height=90))
                bad = R.invalid_code_forms(R.VOCAB_FIELDS[f], work[f])
                if bad:
                    st.warning(f"invalid {labels[f]}: {', '.join(bad)} — allowed: "
                               + R.VOCABULARIES[R.VOCAB_FIELDS[f]].get("hint", ""))
        st.caption("one code per line · ranges like F00-F09 or C00-D48 (ICD-10 / OPCS-4)")
        # codes left over from a previous source are NEVER dropped silently —
        # surface them with an explicit remove action
        for f, v in R.VOCAB_FIELDS.items():
            if v not in legal and work.get(f):
                st.warning(f"this condition still carries {len(work[f])} {labels[f]} "
                           f"code(s) — {', '.join(work[f][:5])}"
                           f"{'…' if len(work[f]) > 5 else ''} — not legal for source "
                           f"'{work['source']}'. Remove them, or switch the source back.")
                if st.button(f"🗑 Remove the {labels[f]} codes", key=f"rm{f}{work['_id']}"):
                    work[f] = []
                    st.session_state.pop(f"dlg_codes_{f}", None)   # widget wasn't drawn this run
                    st.rerun()
        _timing_editor(work)
    elif k == "measure":
        _source_select(work, "measure")
        meas = R.measures_for(work["source"]) or [""]
        cur = work.get("measure", "")
        if cur and cur not in meas:
            meas = [cur] + meas
        c = st.columns([2, 1, 1, 1])
        with c[0]:
            work["measure"] = kselect("Measure", meas, cur, key="dlg_measure")
        with c[1]:
            work["op"] = kselect("Op", S.CMP_OPS, work.get("op", ">="), key="dlg_op")
        with c[2]:
            val = ktext("Value", _s(work.get("value")), key="dlg_value")
        try:
            work["value"] = float(val) if "." in val else int(val)
        except ValueError:
            work["value"] = None
        with c[3]:
            work["unit"] = ktext("Unit", work.get("unit", ""), key="dlg_unit")
        _timing_editor(work)
    elif k == "sample":
        st.caption("ⓘ Counts PEOPLE who have ≥1 sample positioned vs the event. The sample is not selected.")
        se = work["sample_event"]
        ev = se["event"]
        ev["type"] = kselect("Event type", S.EVENT_TYPES, ev["type"], key="dlg_ev_type")
        st.caption(f"codes vocabulary for this event: **{S.EVENT_VOCAB[ev['type']]}**")
        ev["occurrence"] = kradio("Occurrence (defines the index date)", S.OCCURRENCE,
                                  ev["occurrence"], key="dlg_ev_occ", horizontal=True)
        ev["label"] = ktext("Event label", ev.get("label", ""), key="dlg_ev_label")
        ev["codes"] = _lines(karea("Event codes (one per line)", _join(ev.get("codes")),
                                   key="dlg_ev_codes", height=80))
        se["direction"] = kradio("Sample is", S.DIRECTION, se["direction"],
                                 key="dlg_s_dir", horizontal=True)
        wi = se.get("within") or {}
        cw = st.columns(2)
        with cw[0]:
            n = _int(ktext("Within N (blank = any time in that direction)",
                           _s(wi.get("n")), key="dlg_s_n"))
        with cw[1]:
            unit = kselect("Unit", S.WITHIN_UNITS, wi.get("unit", "months"), key="dlg_s_unit")
        se["within"] = {"n": n, "unit": unit}
    elif k == "note":
        work["text"] = karea("Text", work.get("text", ""), key="dlg_text", height=90)

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


@st.dialog("requirement.yaml", width="large")
def yaml_dialog():
    req = st.session_state.req
    text = yaml.dump(S.to_contract(req), sort_keys=False, allow_unicode=True)
    st.code(text, language="yaml")            # st.code has a built-in copy button
    fname = (req.get("ticket") or req.get("project") or "requirement").split()[0]
    c = st.columns(2)
    c[0].download_button("⬇ Download", text, f"{fname}.requirement.yaml", "text/yaml",
                         use_container_width=True, type="primary")
    if c[1].button("Close", use_container_width=True):
        close_modal(); st.rerun()


@st.dialog("Add")
def add_dialog():
    tgt = st.session_state.modal["container"]
    excl = tgt == "__EXCL__"
    where = ("the <b>EXCLUSIONS</b> list (each removed in order)" if excl
             else header_html(find_node(group(), tgt)))
    st.markdown("Add into &nbsp; " + where, unsafe_allow_html=True)
    st.write("")
    # condition = a single criterion (white button)
    if st.button("➕ Condition", use_container_width=True):
        st.session_state.modal = {"mode": "add_leaf", "container": tgt}
        st.session_state.work = S.new_codes()
        st.rerun()
    st.caption("…or a sub-container that combines the items inside it with:")

    def _add_container(op):
        (group()["exclusions"] if excl else find_node(group(), tgt)["members"]).append(S.new_container(op))
        close_modal(); st.rerun()

    c = st.columns(2)
    if c[0].button(f"➕ {OP_FULL['AND']}", use_container_width=True):
        _add_container("AND")
    if c[1].button(f"➕ {OP_FULL['OR']}", use_container_width=True):
        _add_container("OR")
    if st.button("Cancel", use_container_width=True):
        close_modal(); st.rerun()


@st.dialog("Container")
def container_dialog():
    work = st.session_state.work
    work["op"] = kradio("How are the items in this container combined?", S.OPS,
                        work["op"], key="dlg_c_op", format_func=lambda o: OP_FULL[o])
    work["label"] = ktext("Label (optional)", work.get("label", ""), key="dlg_c_label")
    b = st.columns(2)
    if b[0].button("Save", type="primary", use_container_width=True):
        replace_node(group(), work["_id"], work); close_modal(); st.rerun()
    if b[1].button("Cancel", use_container_width=True):
        close_modal(); st.rerun()


# ----------------------------- sidebar -------------------------------------
def sidebar():
    req = st.session_state.req
    with st.sidebar:
        st.title("Health Cohort Builder")
        st.subheader("Project")
        req["project"] = ktext("Title", req["project"], key="w_title")
        # offer the flag-gated UI types; keep a loaded value the UI doesn't
        # offer visible rather than coercing it (validate() flags unknown ones)
        types = list(S.UI_PROJECT_TYPES)
        if req["project_type"] not in types:
            types.append(req["project_type"])
        TYPE_HELP = {"recruitment": "identify people to contact / recruit (e.g. a trial)",
                     "registry": "a cohort for a study or registry dataset",
                     "biobank": "sample-anchored selection (biobank projects)",
                     "other": "anything else — a hint for the downstream builder"}
        req["project_type"] = kradio("Type", types, req["project_type"], key="w_ptype",
                                     captions=[TYPE_HELP.get(t, "not a standard type")
                                               for t in types])
        req["target_n"] = ktext("Target N", req["target_n"], key="w_targetn")
        req["ticket"] = ktext("Ticket (optional)", req.get("ticket", ""), key="w_ticket")

        with st.expander("🔏 **FINALIZE CONTRACT**", expanded=bool(req.get("contract"))):
            hdr = dict(req.get("contract") or {})
            hdr["requested_by"] = ktext("Requested by", hdr.get("requested_by", ""),
                                        key="w_req_by")
            hdr["approved_by"] = ktext("Approved by", hdr.get("approved_by", ""),
                                       key="w_app_by")
            ref = ktext("Extraction spec URI (optional)",
                        (hdr.get("references") or {}).get("extraction_spec", ""),
                        key="w_ref")
            if ref.strip():
                hdr["references"] = {"extraction_spec": ref.strip()}
            else:
                hdr.pop("references", None)
            req["contract"] = {k: v for k, v in hdr.items() if v} or None
            if st.button("🔏 Seal as agreed (version +1, hash body)", use_container_width=True):
                S.seal(req)
                st.rerun()
            hdr = req.get("contract") or {}
            if hdr.get("body_sha256"):
                st.caption(f"id `{hdr.get('id')}` · v{hdr.get('version')} · "
                           f"**{hdr.get('status')}** · {hdr.get('approved_on', '')}")
                if S.hash_status(S.to_contract(req)) == "ok":
                    st.success("hash ✓ body unchanged since sealing")
                else:
                    st.error("body CHANGED since sealing — re-seal to re-approve")

        st.divider()
        st.subheader("Groups")
        st.caption("each group is a complete, self-contained cohort definition")
        names = [g["name"] or f"Group {i+1}" for i, g in enumerate(req["cohorts"])]
        st.session_state.sel = kradio("group", range(len(names)),
                                      min(st.session_state.sel, len(names) - 1),
                                      key="w_group", format_func=lambda i: names[i],
                                      label_visibility="collapsed")
        c = st.columns(3)
        if c[0].button("➕ Add", use_container_width=True, help="add a new empty group"):
            req["cohorts"].append(S.new_group(f"Group {len(req['cohorts'])+1}"))
            st.session_state.sel = len(req["cohorts"]) - 1
            st.session_state._pend_group = st.session_state.sel; st.rerun()
        if c[1].button("⧉ Clone", use_container_width=True,
                       help="duplicate this group as a starting point for a similar cohort"):
            clone = S.clone_group(req["cohorts"][st.session_state.sel])
            req["cohorts"].insert(st.session_state.sel + 1, clone)
            st.session_state.sel += 1
            st.session_state._pend_group = st.session_state.sel; st.rerun()
        if c[2].button("🗑 Remove", use_container_width=True, disabled=len(req["cohorts"]) <= 1):
            req["cohorts"].pop(st.session_state.sel)
            st.session_state.sel = 0
            st.session_state._pend_group = 0; st.rerun()

        st.divider()
        st.subheader("Output")
        contract = S.to_contract(req)
        text = yaml.dump(contract, sort_keys=False, allow_unicode=True)
        fname = (req.get("ticket") or req.get("project") or "requirement").split()[0]
        st.download_button("⬇ Download YAML", text, f"{fname}.requirement.yaml",
                           "text/yaml", use_container_width=True, type="primary")
        if st.button("👁 Preview YAML", use_container_width=True):
            open_modal("yaml", {})
        if st.button("New (blank requirement)", use_container_width=True):
            st.session_state.req = S.new_requirement()
            st.session_state.load_report = None
            st.session_state._wipe_w = True         # widgets re-init from the new req
            st.session_state.sel = 0; st.rerun()
        st.markdown("**📁 Load a requirement.yaml**")
        up = st.file_uploader("Drag a .yaml here or browse", type=["yaml", "yml"],
                              label_visibility="collapsed")
        if up is not None:
            sig = (up.name, up.size)
            if st.session_state.get("_loaded_sig") != sig:       # load each new file once
                try:
                    data = yaml.safe_load(up.getvalue().decode("utf-8"))
                    issues = []
                    gate = S.check_contract(data)
                    st.session_state.req = S.from_contract(data, issues)
                    st.session_state.load_report = {"name": up.name, "gate": gate,
                                                    "draft": issues}
                    st.session_state.sel = 0
                    st.session_state._loaded_sig = sig
                    st.session_state._wipe_w = True   # widgets re-init from the loaded req
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not load: {e}")
        rep = st.session_state.get("load_report")
        if rep:
            if not rep["gate"] and not rep["draft"]:
                st.success(f"✓ {rep['name']} passes the strict contract gate")
            else:
                lines = [f"**{rep['name']} loaded as a DRAFT** — it does not pass "
                         "the strict contract gate:"]
                lines += [f"- {e}" for e in rep["gate"]]
                if rep["draft"]:
                    lines.append("Coercions applied on load:")
                    lines += [f"- {w}" for w in rep["draft"]]
                st.warning("\n".join(lines))


# ----------------------------- main ----------------------------------------
def main():
    init()
    st.markdown(CSS, unsafe_allow_html=True)
    sidebar()
    req = st.session_state.req
    g = group()

    st.markdown("### Group name")
    # per-group key: switching groups re-inits from that group's own name
    g["name"] = ktext("Group name", g["name"], key=f"w_gname_{g['_id']}",
                      label_visibility="collapsed")
    st.caption("ⓘ This group is one complete cohort: an inclusion set, "
               "then exclusions removed in order.")

    with st.container(border=True):
        st.markdown("<div class='sec-head sec-inc'>✓ INCLUSION — base population · KEEP</div>",
                    unsafe_allow_html=True)
        render_member(g, g["inclusion"], is_root=True)
        if st.button("➕ Add inclusion"):
            open_modal("add_to", {}, container=g["inclusion"]["_id"])

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("<div class='sec-head sec-exc'>✕ EXCLUSIONS — removed from the population, in order · REMOVE ↓</div>",
                    unsafe_allow_html=True)
        for i, m in enumerate(g["exclusions"]):
            render_member(g, m, True, g["exclusions"], i, top=True, path=str(i + 1))
        if st.button("➕ Add exclusion"):
            open_modal("add_to", {}, container="__EXCL__")

    errs = S.validate(req)
    contract = S.to_contract(req)
    if errs:
        st.error("Not ready:\n\n" + "\n".join(f"- {e}" for e in errs))
    else:
        reg = R.check_sources(contract)                 # level 2: registry conformance
        notes = S.notes_in(contract)
        if reg:
            st.warning("Registry conformance:\n\n" + "\n".join(f"- {e}" for e in reg))
        if notes:
            locs = " · ".join(f"{where} `[note]`" + (f" '{lbl}'" if lbl else "")
                              for _, lbl, where in notes)
            st.info(f"ⓘ ready to review — {len(req['cohorts'])} group(s), but contains "
                    f"{len(notes)} `note` criterion(s) ({locs}), so it is NOT "
                    "deterministically compilable until they are resolved into "
                    "coded criteria")
        elif not reg:
            st.success(f"✓ ready — {len(req['cohorts'])} cohort group(s), "
                       "deterministically compilable")

    if st.session_state.modal:
        mode = st.session_state.modal["mode"]
        if mode == "edit_container":
            container_dialog()
        elif mode == "add_to":
            add_dialog()
        elif mode == "yaml":
            yaml_dialog()
        else:
            leaf_dialog()


main()
