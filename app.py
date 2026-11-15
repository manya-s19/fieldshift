"""Field Shift dashboard.   Run:  streamlit run app.py"""
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from fs import alerts, backtest, data, models
from fs.config import CROP_COLOR, CROP_LABEL, CROPS, DB_PATH, STATE_NAME, TRAIL_YEARS

st.set_page_config(page_title="Field Shift", page_icon="🌾", layout="wide")

MUTED, GRID, ACCENT = "#898781", "rgba(137,135,129,0.25)", "#6250d6"
PHASE_BADGE = {"BOOM": ":orange-badge[▲ Crowded]", "BUST": ":blue-badge[▼ Under-planted]",
               "NEUTRAL": ":gray-badge[● Balanced]"}
PHASE_TEXT = {"BOOM": "▲ Crowded", "BUST": "▼ Under-planted", "NEUTRAL": "● Balanced"}
OUTLOOKS = {"Drier than normal": "dry", "Near normal": "normal", "Wetter than normal": "wet"}


# ----------------------------------------------------------------------------- cached work

@st.cache_resource
def get_tables(stamp):
    return data.load()


@st.cache_resource(max_entries=24)
def get_season(stamp, target, intentions_key):
    return models.Season(get_tables(stamp), target, dict(intentions_key) if intentions_key else None)


@st.cache_data(show_spinner="Replaying past seasons…")
def get_backtest(stamp):
    return backtest.run(get_tables(stamp))


def base_layout(fig, height):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(font_size=13),
                      legend=dict(orientation="h", y=1.08, x=0))
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


try:
    stamp = DB_PATH.stat().st_mtime
    T = get_tables(stamp)
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

TARGET = T.last_year + 1
names = dict(zip(T.county.fips, T.county.name))

# ----------------------------------------------------------------------------- sidebar

with st.sidebar:
    st.title("🌾 Field Shift")
    st.caption(f"{STATE_NAME} · planning the {TARGET} season")
    fips = st.selectbox("County", T.county.fips, format_func=lambda f: f"{names[f]} County",
                        index=int((T.county.name == "Finney").idxmax()) if "Finney" in set(T.county.name) else 0)
    outlook = OUTLOOKS[st.radio("Season outlook", list(OUTLOOKS), index=1,
                                help="Tilts the odds toward this county's driest or wettest past seasons.")]
    farm_acres = st.number_input("Field size (acres)", 10, 20000, 500, step=10)

    base_market = get_season(stamp, TARGET, None).market
    intentions = None
    with st.expander("What if more farmers pile in?"):
        st.caption("Override the planted-area forecast, e.g. with USDA Prospective Plantings numbers.")
        if not base_market.area_effect.iloc[0]:
            st.caption(":orange[On the loaded data, more planted area has not meant lower prices, so these "
                       "sliders change the crowding label but not the price outlook.]")
        if st.toggle("Use my own numbers"):
            intentions = {}
            for crop in CROPS:
                last_acres = base_market.loc[crop].exp_acres / (1 + base_market.loc[crop].acres_chg)
                chg = st.slider(f"{CROP_LABEL[crop]} area vs last year", -25, 25,
                                int(round(base_market.loc[crop].acres_chg * 100)), format="%d%%")
                intentions[crop] = last_acres * (1 + chg / 100)

season = get_season(stamp, TARGET, tuple(sorted(intentions.items())) if intentions else None)
ranked = season.county(fips, outlook)
best = ranked.iloc[0]
county = names[fips]

if T.source != "real":
    st.warning("**Sample data.** Every number on this page is simulated so the app can run before real data is "
               "loaded. Run `pipeline/fetch_power.py` and `pipeline/fetch_nass.py` to switch to NASA and USDA data.",
               icon="⚠️")

tab_rec, tab_cycle, tab_map, tab_bt, tab_about = st.tabs(
    ["Recommendation", "Market cycles", "Regional stress", "Backtest", "How it works"])

# ----------------------------------------------------------------------------- recommendation

with tab_rec:
    left, right = st.columns([5, 3], gap="large")
    with left:
        with st.container(border=True):
            st.caption(f"{county} County · {TARGET} season · best bet")
            st.markdown(f"## {CROP_LABEL[best.crop]} &nbsp; {PHASE_BADGE[best.phase]}")
            a, b, c, d = st.columns(4)
            a.metric("Typical margin", f"{alerts.money(best.p50)}/ac")
            b.metric("Bad year", f"{alerts.money(best.p10)}/ac", help="1 season in 10 is worse than this.")
            c.metric("Good year", f"{alerts.money(best.p90)}/ac", help="1 season in 10 is better than this.")
            d.metric("Chance of a loss", f"{best.loss_odds:.0%}")
            for line in alerts.reasons(best, outlook):
                st.markdown(f"- {line}")
            st.markdown(f"On **{farm_acres:,} acres** that is about **{alerts.money(best.p50 * farm_acres)}** in a "
                        f"typical year, **{alerts.money(best.p10 * farm_acres)}** in a bad one.")
            if len(ranked) > 1 and best.score > 0 and ranked.iloc[1].score >= 0.8 * best.score:
                st.info(f"{CROP_LABEL[ranked.iloc[1].crop]} is close behind. Splitting roughly 60/40 spreads the "
                        f"risk, and keeps everyone here from planting the same crop.", icon="↔️")

        st.markdown("#### All crops: margin range per acre")
        fig = go.Figure()
        order = ranked.crop.tolist()[::-1]
        for r in ranked.itertuples():
            name = CROP_LABEL[r.crop]
            fig.add_trace(go.Scatter(x=[r.p10, r.p90], y=[name, name], mode="lines", hoverinfo="skip",
                                     line=dict(color=CROP_COLOR[r.crop], width=12), showlegend=False))
            fig.add_trace(go.Scatter(
                x=[r.p50], y=[name], mode="markers+text", showlegend=False,
                marker=dict(size=16, color="white", line=dict(color=CROP_COLOR[r.crop], width=3)),
                text=[f"<b>{alerts.money(r.p50)}</b>"], textposition="top center",
                hovertemplate=(f"<b>{name}</b><br>Bad year {alerts.money(r.p10)}<br>Typical {alerts.money(r.p50)}"
                               f"<br>Good year {alerts.money(r.p90)}<br>Chance of loss {r.loss_odds:.0%}"
                               "<extra></extra>")))
        fig.add_vline(x=0, line_color=MUTED, line_width=1)
        fig.update_yaxes(categoryorder="array", categoryarray=[CROP_LABEL[c] for c in order])
        fig.update_xaxes(title_text="$ per acre · bar = bad year to good year, circle = typical", tickprefix="$")
        st.plotly_chart(base_layout(fig, 90 + 62 * len(ranked)), width="stretch")

        table = pd.DataFrame({
            "Crop": [CROP_LABEL[c] for c in ranked.crop],
            "Market": [PHASE_TEXT[p] for p in ranked.phase],
            "Typical $/ac": ranked.p50.map(alerts.money), "Bad year $/ac": ranked.p10.map(alerts.money),
            "Good year $/ac": ranked.p90.map(alerts.money),
            "Chance of loss": ranked.loss_odds * 100,
            "Yield (bu/ac)": ranked.exp_yield, "Price outlook ($/bu)": ranked.exp_price,
            "Cost $/ac": ranked.cost})
        money_col = st.column_config.NumberColumn(format="$%.0f")
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "Cost $/ac": money_col,
            "Chance of loss": st.column_config.NumberColumn(format="%.0f%%"),
            "Yield (bu/ac)": st.column_config.NumberColumn(format="%.0f"),
            "Price outlook ($/bu)": st.column_config.NumberColumn(format="$%.2f")})

    with right:
        st.markdown("#### Alert channel")
        sms = alerts.sms_text(county, TARGET, ranked, outlook)
        st.markdown(f"""
<div style="max-width:320px;margin:0 auto;border:10px solid #1a1a19;border-radius:34px;background:#f4f4f2;
            padding:18px 14px 26px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
  <div style="text-align:center;color:#52514e;font-size:12px;margin-bottom:12px;">Field Shift Alerts<br>
       <span style="color:#898781;">Text message · today</span></div>
  <div style="background:#e4e3df;color:#0b0b0b;border-radius:18px 18px 18px 4px;padding:10px 13px;
              font-size:14.5px;line-height:1.4;">{html.escape(sms)}</div>
  <div style="text-align:right;margin-top:12px;"><span style="background:#2a78d6;color:#fff;
       border-radius:18px 18px 4px 18px;padding:8px 13px;font-size:14.5px;display:inline-block;">MORE</span></div>
  <div style="background:#e4e3df;color:#0b0b0b;border-radius:18px 18px 18px 4px;padding:10px 13px;margin-top:12px;
              font-size:14.5px;line-height:1.4;">{html.escape(alerts.cycle_line(best))}</div>
</div>""", unsafe_allow_html=True)
        st.caption(f"Mock-up of the text a farmer receives ({len(sms)} characters, two SMS segments at most). "
                   "`fs/alerts.py` builds the message; `send_sms` is the hook for Twilio.")

# ----------------------------------------------------------------------------- market cycles

with tab_cycle:
    crop = st.segmented_control("Crop", CROPS, default=best.crop, format_func=CROP_LABEL.get) or best.crop
    hist = models.market_features(T.market)
    hist = hist[hist.crop == crop].sort_values("year")
    fc = season.market.loc[crop]
    st.markdown(f"**{alerts.cycle_line(pd.Series({**fc.to_dict(), 'crop': crop}))}**")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09, row_heights=[0.55, 0.45],
                        subplot_titles=("Harvest price ($ per bushel)",
                                        f"Planted area vs its {TRAIL_YEARS}-year normal (%)"))
    color = CROP_COLOR[crop]
    fig.add_trace(go.Scatter(x=hist.year, y=hist.price, mode="lines+markers", name="Price",
                             line=dict(color=color, width=2), marker=dict(size=6),
                             hovertemplate="%{x}: $%{y:.2f}/bu<extra></extra>"), 1, 1)
    fig.add_trace(go.Scatter(x=[hist.year.iloc[-1], TARGET], y=[hist.price.iloc[-1], fc.exp_price],
                             mode="lines+markers+text", name="Forecast", line=dict(color=color, width=2, dash="dot"),
                             marker=dict(size=[0, 11], color="white", line=dict(color=color, width=2)),
                             text=["", f"<b>${fc.exp_price:.2f}</b>"], textposition="top center",
                             hovertemplate="%{x} forecast: $%{y:.2f}/bu<extra></extra>"), 1, 1)
    fig.add_trace(go.Bar(x=hist.year, y=hist.acre_anom * 100, name="Planted area", marker_color="#b5b3aa",
                         hovertemplate="%{x}: %{y:+.1f}% vs normal<extra></extra>"), 2, 1)
    fig.add_trace(go.Bar(x=[TARGET], y=[fc.acre_anom * 100], name="Forecast area",
                         marker=dict(color=color, pattern_shape="/"),
                         hovertemplate="%{x} forecast: %{y:+.1f}% vs normal<extra></extra>"), 2, 1)

    # shade the crowded / under-planted years, one label per run of years
    marks = pd.concat([hist[["year", "phase"]], pd.DataFrame({"year": [TARGET], "phase": [fc.phase]})])
    run_start, prev = None, None
    for yr, ph in list(zip(marks.year, marks.phase)) + [(None, None)]:
        if ph != prev:
            if prev in ("BOOM", "BUST"):
                fig.add_vrect(x0=run_start - 0.5, x1=last_yr + 0.5, line_width=0,
                              fillcolor="#ec835a" if prev == "BOOM" else "#2a78d6", opacity=0.16,
                              annotation_text="▲" if prev == "BOOM" else "▼", annotation_position="top left",
                              annotation_font_size=11)
            run_start, prev = yr, ph
        last_yr = yr
    fig.add_hline(y=0, line_color=MUTED, line_width=1, row=2, col=1)
    fig.update_yaxes(tickprefix="$", row=1, col=1)
    fig.update_yaxes(ticksuffix="%", row=2, col=1)
    fig.update_layout(showlegend=False, bargap=0.25)
    st.plotly_chart(base_layout(fig, 520), width="stretch")
    st.caption("Shaded years: ▲ crowded (area well above normal right after a price jump, so a glut tends to "
               "follow) · ▼ under-planted (area well below normal after a price drop, so supply tends to tighten). "
               f"The {TARGET} point is the forecast "
               f"({'your planted-area numbers' if intentions else 'supply-response model'}).")

    if season.market.area_effect.iloc[0]:
        st.caption(f"Price model: each 10% of planted area above normal has gone with a "
                   f"{abs(season.market.price_slope.iloc[0]) * 10:.1f}% lower price.")
    else:
        st.info("On the loaded data, years with more planted area did not have lower prices (demand shocks "
                "dominate). The price outlook is therefore a return to each crop's 10-year normal, and the "
                "crowded / under-planted labels are a warning sign only.", icon="ℹ️")
    st.markdown(f"#### All crops, {TARGET}")
    mk = season.market
    st.dataframe(pd.DataFrame({
        "Crop": [CROP_LABEL[c] for c in mk.index], "Market": [PHASE_TEXT[p] for p in mk.phase],
        "Planted area vs last year": mk.acres_chg * 100, "Last price ($/bu)": mk.last_price,
        "Price outlook ($/bu)": mk.exp_price, "Outlook vs last year": (mk.exp_price / mk.last_price - 1) * 100,
    }), hide_index=True, width="stretch", column_config={
        "Planted area vs last year": st.column_config.NumberColumn(format="%+.1f%%"),
        "Outlook vs last year": st.column_config.NumberColumn(format="%+.1f%%"),
        "Last price ($/bu)": st.column_config.NumberColumn(format="$%.2f"),
        "Price outlook ($/bu)": st.column_config.NumberColumn(format="$%.2f")})

# ----------------------------------------------------------------------------- regional stress

with tab_map:
    stress = models.soil_stress(T.weather, T.last_year).merge(T.county, on="fips")
    top = {f: season.county(f, outlook).iloc[0] for f in stress.fips}
    stress["Best bet"] = [CROP_LABEL[top[f].crop] for f in stress.fips]
    stress["Typical $/ac"] = [top[f].p50 for f in stress.fips]
    stress["Typical"] = stress["Typical $/ac"].map(alerts.money)
    st.markdown(f"#### Spring soil moisture vs each county's normal, {T.last_year}")
    lim = max(2.0, float(stress.soil_z.abs().max()))
    outline = [(-102.05, 37.0), (-94.62, 37.0), (-94.61, 39.11), (-94.88, 39.4), (-95.02, 39.7), (-95.31, 40.0),
               (-102.05, 40.0), (-102.05, 37.0)]                     # simplified Kansas border
    label_pos = []                    # label above a county unless its nearest neighbour sits above it
    for r in stress.itertuples():
        others = stress[stress.fips != r.fips]
        near = others.loc[((others.lat - r.lat) ** 2 + (others.lon - r.lon) ** 2).idxmin()]
        label_pos.append("top center" if (r.lat, -r.lon) > (near.lat, -near.lon) else "bottom center")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[p[0] for p in outline], y=[p[1] for p in outline], mode="lines",
                             line=dict(color=MUTED, width=1.5), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=stress.lon, y=stress.lat, mode="markers+text", text=stress.name,
        textposition=label_pos,
        showlegend=False, customdata=stress[["name", "soil_z", "soil_wet_spring", "Best bet", "Typical $/ac"]],
        marker=dict(size=24, color=stress.soil_z, cmin=-lim, cmax=lim, line=dict(color=MUTED, width=1),
                    colorscale=[[0, "#eb6834"], [0.5, "#f0efec"], [1, "#2a78d6"]],
                    colorbar=dict(title="Drier ← normal → wetter", title_side="right", thickness=12, len=0.8)),
        hovertemplate=("<b>%{customdata[0]} County</b><br>Soil moisture %{customdata[1]:+.1f}σ vs normal"
                       "<br>Wetness %{customdata[2]:.2f}<br>Best bet: %{customdata[3]}"
                       "<br>Typical $%{customdata[4]:.0f}/ac<extra></extra>")))
    fig.update_xaxes(visible=False, range=[-102.6, -94.0])
    fig.update_yaxes(visible=False, range=[36.7, 40.4], scaleanchor="x", scaleratio=1.28)
    st.plotly_chart(base_layout(fig, 470), width="stretch")
    st.caption("Root-zone soil wetness in March-April (NASA POWER `GWETROOT`), in standard deviations from the "
               "county's own history. Orange = drier than normal, blue = wetter. Hover a county for its best bet.")
    st.dataframe(stress.assign(County=stress.name)[["County", "soil_wet_spring", "soil_z", "Best bet", "Typical"]]
                 .sort_values("soil_z"), hide_index=True, width="stretch", column_config={
        "soil_wet_spring": st.column_config.NumberColumn("Soil wetness (0-1)", format="%.2f"),
        "soil_z": st.column_config.NumberColumn("vs normal (σ)", format="%+.1f"),
        "Typical": st.column_config.TextColumn("Typical $/ac")})

# ----------------------------------------------------------------------------- backtest

with tab_bt:
    bt = get_backtest(stamp)
    summ = backtest.summarise(bt)
    y0, y1 = int(bt.year.min()), int(bt.year.max())
    st.markdown(f"#### Would following the advice have paid? {y0}-{y1}, {bt.fips.nunique()} counties")
    st.caption(f"{len(bt) // 3} county-seasons scored: those where USDA published a yield for every strategy's pick. "
               "Margins are returns over operating costs, on dryland-basis yields.")
    if T.source != "real":
        st.warning("On sample data this only shows that the pipeline runs. The simulated market contains a cobweb "
                   "by construction, so the result below is not evidence. Load real data before quoting it.",
                   icon="⚠️")
    fs_, nv = summ.loc["fieldshift"], summ.loc["naive"]
    a, b, c = st.columns(3)
    a.metric("Field Shift, average margin", f"{alerts.money(fs_.avg_margin)}/ac",
             f"{fs_.avg_margin / nv.avg_margin - 1:+.1%} vs chasing last year's price" if nv.avg_margin > 0 else None)
    b.metric("In dry seasons", f"{alerts.money(fs_.dry_year_margin)}/ac",
             f"{alerts.money(fs_.dry_year_margin - nv.dry_year_margin)}/ac vs chasing")
    c.metric("Worst single year", f"{alerts.money(fs_.worst_year)}/ac",
             f"{alerts.money(fs_.worst_year - nv.worst_year)}/ac vs chasing")

    l, r = st.columns(2, gap="large")
    style = {"naive": dict(color=MUTED, dash="solid"), "climate": dict(color="#52514e", dash="dash"),
             "fieldshift": dict(color=ACCENT, dash="solid")}
    with l:
        st.markdown("**Average margin by strategy ($/acre)**")
        fig = go.Figure()
        labels = [backtest.STRATEGY_LABEL[s] for s in summ.index]
        for col, nm, colr in (("avg_margin", "All seasons", "#2a78d6"), ("dry_year_margin", "Dry seasons", "#eb6834")):
            fig.add_trace(go.Bar(x=labels, y=summ[col], name=nm, marker_color=colr,
                                 text=[alerts.money(v) for v in summ[col]], textposition="outside",
                                 hovertemplate="%{x}<br>" + nm + ": $%{y:.0f}/ac<extra></extra>"))
        fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.06)
        fig.update_yaxes(tickprefix="$", rangemode="tozero")
        st.plotly_chart(base_layout(fig, 380), width="stretch")
    with r:
        st.markdown("**Margin by year ($/acre, average across counties)**")
        yearly = bt.groupby(["strategy", "year"]).margin.mean().unstack(0)
        fig = go.Figure()
        for s in ["naive", "climate", "fieldshift"]:
            fig.add_trace(go.Scatter(x=yearly.index, y=yearly[s], mode="lines", name=backtest.STRATEGY_LABEL[s],
                                     line=dict(width=3 if s == "fieldshift" else 2, **style[s]),
                                     hovertemplate="%{x}: $%{y:.0f}/ac<extra>" + backtest.STRATEGY_LABEL[s] + "</extra>"))
        fig.update_yaxes(tickprefix="$")
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(base_layout(fig, 380), width="stretch")

    st.dataframe(pd.DataFrame({
        "Strategy": [backtest.STRATEGY_LABEL[s] for s in summ.index],
        "Average $/ac": summ.avg_margin.map(alerts.money), "Dry seasons $/ac": summ.dry_year_margin.map(alerts.money),
        "Worst year $/ac": summ.worst_year.map(alerts.money), "Seasons at a loss": summ.loss_share * 100,
    }), hide_index=True, width="stretch", column_config={
        "Seasons at a loss": st.column_config.NumberColumn(format="%.0f%%")})
    st.caption("Walk-forward: for every year the models are refitted on earlier years only, one crop is picked per "
               "county, and the pick is scored with that year's actual yield and price. Dry seasons are each "
               "county's driest third. 'Climate fit only' is Field Shift with the cycle signal switched off.")

# ----------------------------------------------------------------------------- about

with tab_about:
    st.markdown(f"""
#### What the recommendation is made of
0. **Dryland footing.** USDA county yields mix irrigated and dryland fields. Each crop's yield is scaled by
   the county's typical dryland-to-all-fields ratio, so thirsty irrigated crops are not flattered.
1. **Climate fit.** For each crop, yield is regressed on growing-season rain, heat days (above 35 °C), a
   technology trend and a county effect. Every past season in the county is then replayed as a possible
   next season, so the answer is a range, not a single number.
2. **Market cycle.** Farmers tend to plant what paid last year. The supply-response model forecasts how much
   area each crop will get, and the price model turns "more area than normal" into a lower expected harvest
   price. A crop is flagged **crowded** when area is well above its {TRAIL_YEARS}-year normal right after a
   price jump, and **under-planted** in the mirror case.
3. **Margin.** Yield × expected price − cost per acre, simulated a few thousand times. Crops are ranked by
   typical margin minus half the gap down to a bad year, so a crop that is slightly less profitable but far
   steadier can win.

#### Data
| Table | Real source | Script |
|---|---|---|
| Weather, soil wetness | NASA POWER daily API (`PRECTOTCORR`, `T2M_MAX`, `GWETROOT`) | `pipeline/fetch_power.py` |
| County yield and area, US planted area, Kansas prices | USDA NASS QuickStats | `pipeline/fetch_nass.py` |
| Cost per acre | USDA ERS Commodity Costs and Returns | edit `data/raw/cost.csv` |

Currently loaded: **{'real data' if T.source == 'real' else 'simulated sample data'}**.

#### Known limits
- Prices are state-level and applied to every county; costs are regional.
- The crowding signal is a forecast of planted area, so read it as a lean, not a measurement. Swap in USDA
  Prospective Plantings (sidebar) or satellite greenness (MODIS NDVI) once the season starts.
- Winter wheat is sown the autumn before; treat its ranking as next autumn's decision.
- One crop per field per year. Rotations, irrigation and crop insurance are not modelled.
""")
