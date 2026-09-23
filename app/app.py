import sys
from pathlib import Path
import pandas as pd
import altair as alt
import pydeck as pdk
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.country_coords import COUNTRY_COORDS, add_coords

PROC = ROOT / "data" / "processed"
BH_LAT, BH_LON = COUNTRY_COORDS["BH"]

# dark palette
TEAL, RED, INK = "#4FB8BE", "#F2536B", "#ECEEF1"
GREY_BASE, GREY_SEL = "#3A424E", "#CBD1D8"
BG = "#10151B"

st.set_page_config(page_title="Bahrain Transit Corridors", layout="wide")

@st.cache_data
def load_monthly():
    df = pd.read_parquet(PROC / "corridors_hs87.parquet")
    df["year"] = df["period"].dt.year
    return df

@st.cache_data
def load_names():
    from src.corridors import iso_name_map
    return iso_name_map()

def styled(chart):
    """Dark theme for Altair charts."""
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

monthly = load_monthly()
names = load_names()
years = sorted(monthly["year"].unique())

# ---------- header ----------
st.title(
    "Bahrain Transit Corridors — Vehicles & parts (HS 87)",
    help="**Source:** [Bahrain Open Data Portal (data.gov.bh)](https://www.data.gov.bh) — "
         "Foreign Trade: imports & re-exports, HS chapter 87.",
)
st.caption("Estimated origin → Bahrain → destination re-export corridors. "
           "Statistical estimates, not tracked shipments.")

# ---------- sidebar controls ----------
st.sidebar.header("Controls")
year_opt = st.sidebar.selectbox("Year", ["All years"] + [str(y) for y in years])
top_n = st.sidebar.slider("Corridors to show on map", 20, 300, 30, step=10)

# ---------- filter + aggregate ----------
d = monthly if year_opt == "All years" else monthly[monthly["year"] == int(year_opt)]
totals = d.groupby(["origin", "dest"])["est_value"].sum().reset_index()
totals["origin_name"] = totals["origin"].map(names)
totals["dest_name"] = totals["dest"].map(names)
totals = add_coords(totals).dropna(subset=["o_lat", "o_lon", "d_lat", "d_lon"])

# ---------- KPI cards ----------
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

# ---------- map data ----------
top = totals.sort_values("est_value", ascending=False).head(top_n).copy()
top["w"] = 1 + 6 * (top["est_value"] / top["est_value"].max())
top["route"] = top["origin_name"] + " → Bahrain → " + top["dest_name"]
top["usd_m"] = (top["est_value"] / 1e6).round(1)

IMPORT_COL = [79, 184, 190]     # bright teal — origin → Bahrain
REEXPORT_COL = [242, 83, 107]   # bright red  — Bahrain → destination

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

# ---------- map + side panel ----------
eyebrow("Global flows")

map_col, panel_col = st.columns([3, 1])
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
    tbl = top.head(10)[["route", "usd_m"]].rename(
        columns={"route": "Corridor", "usd_m": "US$M"})

    maxv = top["usd_m"].max()
    rows_html = ""
    for _, r in top.head(10).iterrows():
        pct = r["usd_m"] / maxv * 100
        label = f"{r['route']}"
        rows_html += (
            f"<div style='margin-bottom:11px'>"
            f"<div style='display:flex;justify-content:space-between;gap:10px;"
            f"font-size:0.82rem;color:#ECEEF1;margin-bottom:4px'>"
            f"<span title='{r['route']}' style='overflow:hidden;text-overflow:ellipsis;"
            f"white-space:nowrap'>{label}</span>"
            f"<span style='color:#A7B0BD;flex:none'>${r['usd_m']:,.1f}M</span></div>"
            f"<div style='height:5px;background:#232932;border-radius:3px'>"
            f"<div style='height:100%;width:{pct:.1f}%;background:{TEAL};"
            f"border-radius:3px'></div></div>"
            f"</div>"
        )
    st.markdown(rows_html, unsafe_allow_html=True)

st.divider()

# ---------- bar charts ----------
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

# shared x-axis max so both plots are identical width
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

# ---------- yearly trend ----------
eyebrow("Trend")

yearly = monthly.groupby("year")["est_value"].sum().reset_index()
yearly["usd_m"] = yearly["est_value"] / 1e6
sel_year = None if year_opt == "All years" else int(year_opt)

color_enc = (alt.condition(f"datum.year == {sel_year}", alt.value(GREY_SEL), alt.value(GREY_BASE))
             if sel_year else alt.value(GREY_BASE))

trend = (
    alt.Chart(yearly).mark_bar()
    .encode(
        x=alt.X("year:O", title=None),
        y=alt.Y("usd_m:Q", title="US$ million"),
        color=color_enc,
        tooltip=[alt.Tooltip("year:O", title="Year"),
                 alt.Tooltip("usd_m:Q", title="US$M", format=",.1f")],
    ).properties(height=240, title="Re-export value by year (all corridors)")
)
st.altair_chart(styled(trend), use_container_width=True)
st.caption("Bars, KPIs and map reflect the selected year; the yearly trend always shows full history "
           "(the selected year is highlighted in a lighter shade).")