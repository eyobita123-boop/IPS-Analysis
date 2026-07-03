import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from pathlib import Path

# ========== PAGE CONFIG ==========
st.set_page_config(
    page_title="EthSwitch Dashboard",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "ETH switching analytics for IPS and QR transactions. Built for fast insights and better decision-making."
    }
)

# ========== DATA LOADING ==========
DATA_PREFIXES = ["data", "qr", "ips"]

@st.cache_data
def load_all_data(folder_path):
    path = Path(folder_path)
    if not path.exists():
        return None

    excel_files = sorted([f for f in path.glob("*.xlsx") if not f.name.startswith("~$")])
    if not excel_files:
        return None

    records = []
    for file in excel_files:
        try:
            date = pd.to_datetime(file.stem).date()
        except Exception:
            continue

        df_raw = pd.read_excel(file, header=None)
        header_row_idx = None
        for i, row in df_raw.iterrows():
            if any(str(val).strip().upper() == "BANK" for val in row if pd.notna(val)):
                header_row_idx = i
                break
        if header_row_idx is None:
            header_row_idx = 6

        headers = df_raw.iloc[header_row_idx].fillna("").astype(str).str.strip().str.upper()
        df_day = df_raw.iloc[header_row_idx + 1 :].copy()
        df_day.columns = headers

        def find_col(keywords):
            for col in df_day.columns:
                if all(keyword in col for keyword in keywords):
                    return col
            return None

        bank_col = find_col(["BANK"])
        in_txn_col = find_col(["DESTINATION", "TRANSACTION"]) or find_col(["NO", "TRANSACTIONS"])
        in_val_col = find_col(["DESTINATION", "VALUES"])
        out_txn_col = find_col(["SOURCE", "TRANSACTION"])
        out_val_col = find_col(["SOURCE", "VALUES"])

        if not all([bank_col, in_txn_col, in_val_col, out_txn_col, out_val_col]):
            df_day = df_raw.iloc[header_row_idx + 1 :, [1, 2, 3, 4, 5]]
            df_day.columns = ["Bank", "Inbound Txns", "Inbound Value", "Outbound Txns", "Outbound Value"]
        else:
            df_day = df_day[[bank_col, in_txn_col, in_val_col, out_txn_col, out_val_col]]
            df_day.columns = ["Bank", "Inbound Txns", "Inbound Value", "Outbound Txns", "Outbound Value"]

        df_day = df_day.dropna(subset=["Bank"]).copy()
        df_day["Bank"] = df_day["Bank"].astype(str).str.strip()
        df_day = df_day[~df_day["Bank"].str.upper().str.contains("TOTAL")]
        df_day["Date"] = date
        records.append(df_day)

    if not records:
        return None

    df = pd.concat(records, ignore_index=True)
    for col in ["Inbound Value", "Outbound Value", "Inbound Txns", "Outbound Txns"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["Total Value"] = df["Inbound Value"] + df["Outbound Value"]
    df["Net Flow"] = df["Inbound Value"] - df["Outbound Value"]
    return df


def discover_data_folders(root_path):
    return sorted(
        [d for d in root_path.iterdir() if d.is_dir() and any(d.name.lower().startswith(prefix) for prefix in DATA_PREFIXES)]
    )


def format_etb(value, scale=1, digits=2):
    return f"{value / scale:,.{digits}f}"


def styled_bar(x, y, title, xlabel, color=None, text_format=None):
    fig = go.Figure(go.Bar(
        x=x,
        y=y,
        orientation='h',
        text=text_format(x) if text_format else x,
        textposition='outside',
        marker_color=color or '#4682B4',
        hovertemplate='%{y}: %{x}<extra></extra>'
    ))
    fig.update_layout(
        title=title,
        xaxis_title=xlabel,
        template='plotly_white',
        height=520,
        margin=dict(l=170, r=50, t=60, b=40)
    )
    return fig


# ========== DISCOVER ALL DATA SOURCES ==========
project_dir = Path.cwd()
data_dirs = discover_data_folders(project_dir)

all_data_sources = {}
for data_dir in data_dirs:
    df = load_all_data(data_dir)
    if df is not None and not df.empty:
        all_data_sources[data_dir.name] = df

if not all_data_sources:
    st.error("No valid data folders found. Please add a folder starting with 'data', 'qr', or 'ips'.")
    st.stop()

# ========== SIDEBAR CONTROLS ==========
st.sidebar.title("💳 IPS & QR Insights")
st.sidebar.markdown("Use the filters below to focus on date ranges, banks, and the dataset you want to analyze.")

data_source = st.sidebar.radio("📂 Data Source", list(all_data_sources.keys()), horizontal=True)

df_active = all_data_sources[data_source].copy()
df_active["Bank"] = df_active["Bank"].astype(str).str.strip()

dates_list = sorted(df_active["Date"].dropna().unique())
min_date, max_date = dates_list[0], dates_list[-1]

view_mode = st.sidebar.radio(
    "🔍 View mode",
    ["Single Date", "All Days Summary", "Date Range"]
)

if view_mode == "Single Date":
    selected_date = st.sidebar.selectbox("Pick a date", dates_list, index=len(dates_list) - 1)
    df_view = df_active[df_active["Date"] == selected_date].copy()
    title_suffix = f" – {selected_date}"
    trend_data = df_view.copy()

elif view_mode == "All Days Summary":
    df_view = df_active.groupby("Bank", as_index=False).agg({
        "Inbound Value": "sum",
        "Outbound Value": "sum",
        "Inbound Txns": "sum",
        "Outbound Txns": "sum",
        "Total Value": "sum",
        "Net Flow": "sum",
    })
    title_suffix = " – All Days Combined"
    trend_data = df_active.copy()

else:
    date_range = st.sidebar.date_input(
        "Select date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range

    mask = (df_active["Date"] >= start_date) & (df_active["Date"] <= end_date)
    df_range = df_active[mask]
    df_view = df_range.groupby("Bank", as_index=False).agg({
        "Inbound Value": "sum",
        "Outbound Value": "sum",
        "Inbound Txns": "sum",
        "Outbound Txns": "sum",
        "Total Value": "sum",
        "Net Flow": "sum",
    })
    title_suffix = f" – {start_date} to {end_date}"
    trend_data = df_range.copy()

available_banks = sorted(df_view["Bank"].unique())
selected_banks = st.sidebar.multiselect(
    "Filter banks",
    available_banks,
    default=available_banks[:10] if len(available_banks) > 10 else available_banks
)
if selected_banks:
    df_view = df_view[df_view["Bank"].isin(selected_banks)].copy()
    trend_data = trend_data[trend_data["Bank"].isin(selected_banks)].copy()

force_dashen = st.sidebar.checkbox("Always include Dashen Bank in Top 10", value=True)

file_count = len([f for f in Path(project_dir / data_source).glob("*.xlsx") if not f.name.startswith("~$")])
bank_count = df_active["Bank"].nunique()

# ========== COMMON CALCULATIONS ==========
if df_view["Total Value"].sum() > 0:
    df_view["Market Share (%)"] = (df_view["Total Value"] / df_view["Total Value"].sum()) * 100
else:
    df_view["Market Share (%)"] = 0

top10 = df_view.nlargest(10, "Total Value").copy()
if force_dashen and "Dashen" not in top10["Bank"].values:
    dashen_row = df_view[df_view["Bank"] == "Dashen"]
    if not dashen_row.empty:
        top10 = pd.concat([top10.iloc[:-1], dashen_row])
        top10 = top10.sort_values("Total Value", ascending=False)

# ========== PAGE SELECTION ==========
page = st.sidebar.radio(
    "📊 Navigate",
    ["Overview", "Market Share", "Value Flows", "Transaction Volumes", "Net Flows", "Trends", "Data Explorer"]
)

st.markdown(f"# {data_source} Dashboard{title_suffix}")
st.markdown("---")

# ========== DASHBOARD PAGES ==========
if page == "Overview":
    st.header("📌 Executive Summary")
    total_value = df_view["Total Value"].sum()
    total_txns = df_view["Inbound Txns"].sum() + df_view["Outbound Txns"].sum()
    average_value = (total_value / len(dates_list)) if dates_list else 0
    net_flow = df_view["Net Flow"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Value (ETB)", f"{format_etb(total_value, scale=1e9)} B")
    c2.metric("Total Transactions", f"{total_txns:,.0f}")
    c3.metric("Active Institutions", f"{bank_count}")
    c4.metric("Net Flow (ETB)", f"{format_etb(net_flow, scale=1e6)} M")

    st.markdown("### Snapshot")
    s1, s2, s3 = st.columns(3)
    s1.metric("Data files", file_count)
    s2.metric("Available days", len(dates_list))
    s3.metric("Average daily value", f"{format_etb(average_value, scale=1e9)} B")

    st.markdown("---")
    st.subheader("Top 10 Banks by Total Value")
    if top10.empty:
        st.warning("No bank data available for the selected filters.")
    else:
        bar_fig = styled_bar(
            x=top10["Total Value"].iloc[::-1] / 1e6,
            y=top10["Bank"].iloc[::-1],
            title="Top 10 Banks by Total Value",
            xlabel="Million ETB",
            color="#3CB371",
            text_format=lambda x: [f"{v:,.1f} M" for v in x]
        )
        st.plotly_chart(bar_fig, use_container_width=True)
        st.dataframe(
            top10[["Bank", "Total Value", "Net Flow", "Market Share (%)"]]
            .assign(**{
                "Total Value": lambda d: d["Total Value"].map(lambda v: f"{v:,.0f}"),
                "Net Flow": lambda d: d["Net Flow"].map(lambda v: f"{v:,.0f}"),
                "Market Share (%)": lambda d: d["Market Share (%)"].map(lambda v: f"{v:.1f}%")
            })
        )

elif page == "Market Share":
    st.header("🥧 Market Share")
    if top10.empty:
        st.warning("No market share data available.")
    else:
        other_share = max(0, 100 - top10['Market Share (%)'].sum())
        pie_df = pd.DataFrame({
            'Bank': list(top10['Bank']) + ['Others'],
            'Share': list(top10['Market Share (%)']) + [other_share]
        })
        fig_pie = px.pie(
            pie_df,
            values='Share',
            names='Bank',
            title='Share of Total Value (Top 10 + Others)',
            color_discrete_sequence=px.colors.qualitative.Set2
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)
        st.dataframe(top10[['Bank', 'Market Share (%)', 'Total Value']].style.format({
            'Market Share (%)': '{:.1f}%',
            'Total Value': '{:,.0f}'
        }))

elif page == "Value Flows":
    st.header("💸 Inbound vs Outbound Value")
    if top10.empty:
        st.warning("No data available for value flows.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=top10['Bank'], x=top10['Inbound Value'] / 1e6,
            name='Inbound', orientation='h', marker_color='#2E8B57'
        ))
        fig.add_trace(go.Bar(
            y=top10['Bank'], x=top10['Outbound Value'] / 1e6,
            name='Outbound', orientation='h', marker_color='#CD5C5C'
        ))
        fig.update_layout(
            barmode='group',
            title='Inbound vs Outbound Value (M ETB)',
            template='plotly_white',
            height=560,
            margin=dict(l=170, r=50, t=60, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

elif page == "Transaction Volumes":
    st.header("📈 Transaction Volumes")
    if top10.empty:
        st.warning("No transaction volume data available.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=top10['Bank'], x=top10['Inbound Txns'],
            name='Inbound Txns', orientation='h', marker_color='#1E90FF'
        ))
        fig.add_trace(go.Bar(
            y=top10['Bank'], x=top10['Outbound Txns'],
            name='Outbound Txns', orientation='h', marker_color='#FF8C00'
        ))
        fig.update_layout(
            barmode='group',
            title='Transaction Volumes',
            template='plotly_white',
            height=560,
            margin=dict(l=170, r=50, t=60, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

elif page == "Net Flows":
    st.header("⚖️ Net Flows")
    if top10.empty:
        st.warning("No net flow data available.")
    else:
        net_values = top10['Net Flow'] / 1e6
        colors = ['#2E8B57' if v >= 0 else '#CD5C5C' for v in net_values]
        fig = go.Figure(go.Bar(
            x=net_values[::-1],
            y=top10['Bank'].iloc[::-1],
            orientation='h',
            marker_color=colors[::-1],
            text=[f"{v:+.1f} M" for v in net_values[::-1]],
            textposition='outside'
        ))
        fig.update_layout(
            title='Net Flow by Bank (Million ETB)',
            template='plotly_white',
            height=520,
            margin=dict(l=170, r=50, t=60, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

elif page == "Trends":
    st.header("📈 Trends")
    if trend_data.empty:
        st.warning("No trend data available for the selected filters.")
    else:
        daily_totals = trend_data.groupby("Date").agg(
            Total_Value=("Total Value", "sum"),
            In_Txns=("Inbound Txns", "sum"),
            Out_Txns=("Outbound Txns", "sum")
        ).reset_index()
        daily_totals["Total_Txns"] = daily_totals["In_Txns"] + daily_totals["Out_Txns"]

        fig1 = px.line(
            daily_totals,
            x="Date",
            y="Total_Value",
            title="Daily Total Value (ETB)",
            markers=True
        )
        fig1.update_layout(template='plotly_white')
        st.plotly_chart(fig1, use_container_width=True)

        top5_banks = trend_data.groupby("Bank")["Total Value"].sum().nlargest(5).index
        top5_trend = trend_data[trend_data["Bank"].isin(top5_banks)].groupby(
            ["Date", "Bank"])["Total Value"].sum().reset_index()
        fig2 = px.line(
            top5_trend,
            x="Date",
            y="Total Value",
            color="Bank",
            title="Top 5 Banks — Daily Total Value",
            markers=True
        )
        fig2.update_layout(template='plotly_white')
        st.plotly_chart(fig2, use_container_width=True)

        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=daily_totals["Date"],
            y=daily_totals["In_Txns"],
            name="Inbound Txns",
            mode="lines+markers"
        ))
        fig3.add_trace(go.Scatter(
            x=daily_totals["Date"],
            y=daily_totals["Out_Txns"],
            name="Outbound Txns",
            mode="lines+markers"
        ))
        fig3.update_layout(
            title="Daily Transaction Counts",
            template='plotly_white',
            height=520,
            margin=dict(l=70, r=50, t=60, b=40)
        )
        st.plotly_chart(fig3, use_container_width=True)

elif page == "Data Explorer":
    st.header("🗃️ Data Explorer")
    st.markdown("Use the data explorer to inspect the filtered bank-level results.")
    if df_view.empty:
        st.warning("No records to display for the selected filters.")
    else:
        df_display = df_view.sort_values("Total Value", ascending=False).reset_index(drop=True)
        df_display["Market Share (%)"] = df_display["Market Share (%)"].round(2)
        st.dataframe(df_display)

# ========== FOOTER ==========
st.sidebar.markdown("---")
st.sidebar.caption(f"Source: {data_source} — {len(dates_list)} days, {bank_count} banks")
st.sidebar.caption("Dashboard by Eyob Dereje — [LinkedIn](https://www.linkedin.com/in/eyobderejebekele-bb8a02379)")

