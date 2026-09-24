import sys
from pathlib import Path
import pandas as pd
import altair as alt
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.country_coords import COUNTRY_COORDS, add_coords
from src.ai_chat import ask

PROC = ROOT / "data" / "processed"
BH_LAT, BH_LON = COUNTRY_COORDS["BH"]

TEAL, RED, INK = "#4FB8BE", "#F2536B", "#ECEEF1"
GREY_BASE, GREY_SEL = "#3A424E", "#CBD1D8"
BG = "#10151B"

st.set_page_config(page_title="Bahrain Transit Corridors", layout="wide")

if "chat" not in st.session_state:
    st.session_state.chat = []
    st.session_state.api = []
    st.session_state.chat_open = False
    st.session_state.pending = None

@st.cache_data
def load_monthly():
    df = pd.read_parquet(PROC / "corridors_hs87.parquet")
    df["year"] = df["period"].dt.year
    return df

@st.cache_data
def load_names():
    from src.ai_tools import name_map
    return name_map()

@st.cache_data
def load_ai_df():
    from src.ai_tools import load_named_corridors
    return load_named_corridors()

def styled(chart):
    return (chart
            .configure(background=BG)
            .configure_view(stroke=None)
            .configure_axis(labelColor="#A7B0BD", titleColor="#8A93A0",
                            gridColor="#232932", domainColor="#232932",
                            tickColor="#232932", labelFontSize=11)
            .configure_title(color=INK, fontSize=14, fontWeight=600, anchor="start"))

def eyebrow(text):
    st.markdown(
        f"<div style='font-family:monospace;font-size:0.72rem;letter-spacing:0.16em;"
        f"text-transform:uppercase;color:#9AA3B0;margin:2px 0 6px 2px'>{text}</div>",
        unsafe_allow_html=True,
    )

def top_bar(df, name_col, color, title, xmax):
    agg = (df.groupby(name_col)["est_value"].sum()
             .sort_values(ascending=False).head(10).reset_index())
    agg["usd_m"] = agg["est_value"] / 1e6
    return (
        alt.Chart(agg).mark_bar(color=color)
        .encode(
            x=alt.X("usd_m:Q", title="US$ million", scale=alt.Scale(domain=[0, xmax])),
            y=alt.Y(f"{name_col}:N", sort="-x", title=None,
                    axis=alt.Axis(labelOverlap=False, labelLimit=150,
                                  minExtent=150, maxExtent=150)),
            tooltip=[alt.Tooltip(f"{name_col}:N", title=title),
                     alt.Tooltip("usd_m:Q", title="US$M", format=",.1f")],
        ).properties(height=340, title=title)
    )

def queue_question(question):
    st.session_state.chat.append(("user", question))
    st.session_state.pending = question

monthly = load_monthly()
names = load_names()
years = sorted(monthly["year"].unique())
ai_df = load_ai_df()

# ---------- CSS ----------
st.markdown("""
<style>
div[data-testid="stButton"] button[kind="secondary"] { border-radius: 8px; }
div[data-testid="InputInstructions"] { display: none; }

/* disable browser scroll anchoring so layout shifts don't move the page */
html, body, section[data-testid="stAppViewContainer"], div[data-testid="stMain"] {
    overflow-anchor: none;
}

/* analyst panel: fixed width + sticky within the viewport */
div[data-testid="stColumn"]:has(#analyst-anchor),
div[data-testid="column"]:has(#analyst-anchor) {
    flex: 0 0 380px !important;
    min-width: 340px !important;
    max-width: 390px !important;
    position: sticky !important;
    top: 3.5rem;
    align-self: flex-start;
}
@media (max-width: 900px) {
    div[data-testid="stColumn"]:has(#analyst-anchor),
    div[data-testid="column"]:has(#analyst-anchor) {
        flex: 1 1 100% !important; max-width: 100% !important;
        min-width: 0 !important; position: static !important;
    }
}

/* compact square send button with cyan hover/focus */
div[data-testid="stColumn"]:has(#analyst-anchor) div[data-testid="stFormSubmitButton"] button {
    width: 40px; height: 40px; padding: 0 !important;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.2rem; line-height: 1;
}
div[data-testid="stColumn"]:has(#analyst-anchor) div[data-testid="stFormSubmitButton"] button:hover:not(:disabled),
div[data-testid="stColumn"]:has(#analyst-anchor) div[data-testid="stFormSubmitButton"] button:focus:not(:disabled) {
    border-color: #4FB8BE !important; color: #4FB8BE !important;
}

/* in-thread loading spinner */
.ai-spin {
    width: 13px; height: 13px; border: 2px solid #2C333D;
    border-top-color: #4FB8BE; border-radius: 50%;
    display: inline-block; animation: aispin .7s linear infinite; vertical-align: middle;
}
@keyframes aispin { to { transform: rotate(360deg); } }
</style>
""", unsafe_allow_html=True)

# ---------- sidebar controls ----------
st.sidebar.header("Controls")
year_opt = st.sidebar.selectbox("Year", ["All years"] + [str(y) for y in years])
top_n = st.sidebar.slider("Corridors to show on map", 20, 300, 30, step=10)

st.sidebar.divider()
_open = st.session_state.chat_open
if st.sidebar.button("Close analyst" if _open else "✦  Ask the data",
                     type="secondary" if _open else "primary",
                     use_container_width=True):
    st.session_state.chat_open = not _open
    st.rerun()

# ---------- layout split ----------
if st.session_state.chat_open:
    main_col, chat_col = st.columns([7, 3], gap="medium")
else:
    main_col, chat_col = st.container(), None

# ===================== DASHBOARD =====================
with main_col:
    st.title(
        "Bahrain Transit Corridors — Vehicles & parts (HS 87)",
        help="**Source:** [Bahrain Open Data Portal (data.gov.bh)](https://www.data.gov.bh) — "
             "Foreign Trade: imports & re-exports, HS chapter 87.",
    )
    st.caption("Estimated origin → Bahrain → destination re-export corridors. "
               "Statistical estimates, not tracked shipments.")

    d = monthly if year_opt == "All years" else monthly[monthly["year"] == int(year_opt)]
    totals = d.groupby(["origin", "dest"])["est_value"].sum().reset_index()
    totals["origin_name"] = totals["origin"].map(names)
    totals["dest_name"] = totals["dest"].map(names)
    totals = add_coords(totals).dropna(subset=["o_lat", "o_lon", "d_lat", "d_lon"])

    total_val = totals["est_value"].sum()
    shares = totals["est_value"] / total_val
    hhi = (shares ** 2).sum()
    eff_corridors = int(round(1 / hhi)) if hhi > 0 else 0
    top_share = shares.max() * 100 if len(shares) else 0

    kpis = [
        ("Re-export value", f"${total_val/1e6:,.0f}M", None),
        ("Origin countries", f"{totals['origin'].nunique()}", None),
        ("Destination countries", f"{totals['dest'].nunique()}", None),
        ("Effective corridors", f"{eff_corridors}",
         "1 / HHI — how concentrated the trade is. Low = a few routes dominate."),
        ("Biggest corridor", f"{top_share:.0f}%",
         "Share of all re-export value in the single largest corridor."),
    ]
    for col, (label, value, help_txt) in zip(st.columns(5, gap="small"), kpis):
        with col:
            with st.container(border=True):
                st.metric(label, value, help=help_txt)

    st.divider()

    top = totals.sort_values("est_value", ascending=False).head(top_n).copy()
    top["w"] = 1 + 6 * (top["est_value"] / top["est_value"].max())
    top["route"] = top["origin_name"] + " → Bahrain → " + top["dest_name"]
    top["usd_m"] = (top["est_value"] / 1e6).round(1)

    IMPORT_COL = [79, 184, 190]
    REEXPORT_COL = [242, 83, 107]

    inbound = pd.DataFrame({
        "from_lon": top["o_lon"], "from_lat": top["o_lat"], "to_lon": BH_LON, "to_lat": BH_LAT,
        "w": top["w"], "label": top["route"] + "  ($" + top["usd_m"].astype(str) + "M)",
    })
    outbound = pd.DataFrame({
        "from_lon": BH_LON, "from_lat": BH_LAT, "to_lon": top["d_lon"], "to_lat": top["d_lat"],
        "w": top["w"], "label": top["route"] + "  ($" + top["usd_m"].astype(str) + "M)",
    })

    line_in = pdk.Layer(
        "GreatCircleLayer", data=inbound,
        get_source_position=["from_lon", "from_lat"], get_target_position=["to_lon", "to_lat"],
        get_source_color=IMPORT_COL + [70], get_target_color=IMPORT_COL + [230],
        get_width="w", width_min_pixels=1, pickable=True, auto_highlight=True,
    )
    line_out = pdk.Layer(
        "GreatCircleLayer", data=outbound,
        get_source_position=["from_lon", "from_lat"], get_target_position=["to_lon", "to_lat"],
        get_source_color=REEXPORT_COL + [230], get_target_color=REEXPORT_COL + [70],
        get_width="w", width_min_pixels=1, pickable=True, auto_highlight=True,
    )

    nodes = pd.concat([
        top[["o_lon", "o_lat"]].rename(columns={"o_lon": "lon", "o_lat": "lat"}),
        top[["d_lon", "d_lat"]].rename(columns={"d_lon": "lon", "d_lat": "lat"}),
    ]).dropna().drop_duplicates()

    node_layer = pdk.Layer(
        "ScatterplotLayer", data=nodes,
        get_position=["lon", "lat"], get_radius=22000,
        radius_min_pixels=2, radius_max_pixels=5,
        get_fill_color=[150, 160, 175, 160], stroked=False,
    )
    hub_layer = pdk.Layer(
        "ScatterplotLayer", data=pd.DataFrame([{"lon": BH_LON, "lat": BH_LAT}]),
        get_position=["lon", "lat"], get_radius=60000,
        radius_min_pixels=5, radius_max_pixels=9,
        get_fill_color=[236, 238, 241, 240], stroked=True,
        get_line_color=[79, 184, 190, 255], line_width_min_pixels=1.5,
    )

    view_state = pdk.ViewState(latitude=25, longitude=55, zoom=1.7,
                               min_zoom=1.4, max_zoom=8, pitch=0, bearing=0)

    deck = pdk.Deck(
        layers=[line_in, line_out, node_layer, hub_layer], initial_view_state=view_state,
        map_provider="carto", map_style="dark",
        tooltip={"text": "{label}"}, height=620,
    )

    eyebrow("Global flows")
    map_ratio = [2, 1] if st.session_state.chat_open else [3, 1]
    map_col, panel_col = st.columns(map_ratio)
    with map_col:
        st.pydeck_chart(deck)
    with panel_col:
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:3px'>"
            f"<span style='width:12px;height:12px;border-radius:2px;background:{TEAL};display:inline-block'></span>"
            f"<span style='font-size:0.85rem'>Import Leg : Origin → Bahrain</span></div>"
            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:10px'>"
            f"<span style='width:12px;height:12px;border-radius:2px;background:{RED};display:inline-block'></span>"
            f"<span style='font-size:0.85rem'>Re-export Leg : Bahrain → Destination</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Top corridors**")
        maxv = top["usd_m"].max()
        rows_html = ""
        for _, r in top.head(10).iterrows():
            pct = r["usd_m"] / maxv * 100
            rows_html += (
                f"<div style='margin-bottom:11px'>"
                f"<div style='display:flex;justify-content:space-between;gap:10px;"
                f"font-size:0.82rem;color:#ECEEF1;margin-bottom:4px'>"
                f"<span title='{r['route']}' style='overflow:hidden;text-overflow:ellipsis;"
                f"white-space:nowrap'>{r['route']}</span>"
                f"<span style='color:#A7B0BD;flex:none'>${r['usd_m']:,.1f}M</span></div>"
                f"<div style='height:5px;background:#232932;border-radius:3px'>"
                f"<div style='height:100%;width:{pct:.1f}%;background:{TEAL};"
                f"border-radius:3px'></div></div>"
                f"</div>"
            )
        st.markdown(rows_html, unsafe_allow_html=True)

    st.divider()

    xmax = max(
        totals.groupby("origin_name")["est_value"].sum().max(),
        totals.groupby("dest_name")["est_value"].sum().max(),
    ) / 1e6 * 1.05

    eyebrow("Breakdown")
    b1, b2 = st.columns(2)
    with b1:
        st.altair_chart(styled(top_bar(totals, "origin_name", TEAL, "Where vehicles come from", xmax)),
                        use_container_width=True)
    with b2:
        st.altair_chart(styled(top_bar(totals, "dest_name", RED, "Where Bahrain re-exports to", xmax)),
                        use_container_width=True)

    eyebrow("Trend")
    yearly = monthly.groupby("year")["est_value"].sum().reset_index()
    yearly["usd_m"] = yearly["est_value"] / 1e6
    sel_year = None if year_opt == "All years" else int(year_opt)

    color_enc = (alt.condition(f"datum.year == {sel_year}", alt.value(GREY_SEL), alt.value(GREY_BASE))
                 if sel_year else alt.value(GREY_BASE))

    trend = (
        alt.Chart(yearly).mark_bar()
        .encode(
            x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("usd_m:Q", title="US$ million"),
            color=color_enc,
            tooltip=[alt.Tooltip("year:O", title="Year"),
                     alt.Tooltip("usd_m:Q", title="US$M", format=",.1f")],
        ).properties(height=240, title="Re-export value by year (all corridors)")
    )
    st.altair_chart(styled(trend), use_container_width=True)
    st.caption("Bars, KPIs and map reflect the selected year; the yearly trend always shows full history "
               "(the selected year is highlighted in a lighter shade).")

# ===================== CHAT DRAWER =====================
if chat_col is not None:
    with chat_col:
        st.markdown('<span id="analyst-anchor"></span>', unsafe_allow_html=True)

        h1, h2, h3 = st.columns([6, 2, 1])
        h1.markdown(
            "<div style='font-weight:600;font-size:1.05rem;color:#ECEEF1;padding-top:6px'>"
            "AI Trade Analyst</div>",
            unsafe_allow_html=True,
        )
        if h2.button("Clear", type="tertiary", use_container_width=True):
            st.session_state.chat, st.session_state.api = [], []
            st.session_state.pending = None
            st.rerun()
        if h3.button("✕", type="tertiary", use_container_width=True):
            st.session_state.chat_open = False
            st.rerun()

        # conversation has started if there's a user message OR a query in flight
        started = (st.session_state.pending is not None
                   or any(r == "user" for r, _ in st.session_state.chat))

        convo = st.container(height=470)
        with convo:
            # suggestions ONLY in the true empty state
            if not started:
                st.caption("Ask about origins, destinations, years or corridors — "
                           "answers are grounded in the computed estimates.")
                for ex in ["Who supplies the UAE?", "What changed in 2022?",
                           "Top destinations for Chinese vehicles?"]:
                    if st.button(ex, key=f"ex_{ex}", use_container_width=True):
                        queue_question(ex)
                        st.rerun()

            last_user_idx = max((i for i, (r, _) in enumerate(st.session_state.chat)
                                 if r == "user"), default=-1)
            for i, (role, msg) in enumerate(st.session_state.chat):
                if role == "user":
                    safe = (msg.replace("&", "&amp;").replace("<", "&lt;")
                               .replace(">", "&gt;").replace("$", "&#36;"))
                    st.markdown(
                        f"<div style='background:#1A1F27;border:1px solid #2C333D;"
                        f"border-radius:12px;padding:9px 13px;margin:14px 2px 6px auto;"
                        f"max-width:72%;width:fit-content;font-size:0.9rem;"
                        f"color:#ECEEF1'>{safe}</div>",
                        unsafe_allow_html=True,
                    )
                    if i == last_user_idx:
                        st.markdown('<span id="latest-turn"></span>', unsafe_allow_html=True)
                else:
                    st.markdown(msg.replace("$", "\\$"))
                    st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)

            # in-thread loading indicator (no st.spinner, so nothing lingers)
            if st.session_state.pending:
                st.markdown(
                    "<div style='display:flex;align-items:center;gap:8px;color:#A7B0BD;"
                    "font-size:0.9rem;margin:2px 0 8px 0'>"
                    "<span class='ai-spin'></span>Querying the data…</div>",
                    unsafe_allow_html=True,
                )

            # scroll ONLY the conversation container to the newest message
            if st.session_state.chat:
                # --- lock the browser scroll position across reruns (page must not move on submit) ---
                components.html(
                    """
                    <script>
                    (function () {
                        const w = window.parent;
                        const KEY = "__analyst_scroll_y";
                        // target = the last position the user was actually at
                        const target = (w[KEY] !== undefined) ? w[KEY] : w.scrollY;
                        let n = 0;
                        function pin() {
                            w.scrollTo({ top: target, left: 0, behavior: "instant" });
                            if (n++ < 24) requestAnimationFrame(pin);   // re-pin ~400ms to beat late layout shifts
                        }
                        pin();
                        // save the user's real scroll position once (survives future reruns)
                        if (!w.__analystScrollHook) {
                            w.__analystScrollHook = true;
                            w.addEventListener("scroll", function () { w[KEY] = w.scrollY; }, { passive: true });
                        }
                    })();
                    </script>
                    """,
                    height=0,
                )

        busy = st.session_state.pending is not None
        with st.form("chat_form", clear_on_submit=True, border=False):
            ic1, ic2 = st.columns([8, 1])
            user_q = ic1.text_input("q", label_visibility="collapsed",
                                    placeholder="Ask about the trade data...", disabled=busy)
            sent = ic2.form_submit_button("↑", disabled=busy)
        if sent and user_q:
            queue_question(user_q)
            st.rerun()

        # run the query AFTER the panel has fully rendered the loading state
        if st.session_state.pending:
            qtext = st.session_state.pending
            try:
                answer, st.session_state.api = ask(qtext, ai_df, history=st.session_state.api)
            except Exception as e:
                answer = f"⚠️ Couldn't reach the AI: {e}"
            st.session_state.chat.append(("assistant", answer))
            st.session_state.pending = None
            st.rerun()