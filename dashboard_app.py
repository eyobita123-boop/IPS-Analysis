import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from pathlib import Path

# ========== PAGE CONFIG ==========
st.set_page_config(page_title="EthSwitch IPS/QR Dashboard", layout="wide")

# ========== DATA LOADING (ROBUST – AUTO DETECTS COLUMNS) ==========
@st.cache_data
def load_all_data(folder="data"):
    """
    Reads all .xlsx files from a folder.
    Automatically finds the header row (containing 'BANK') and maps columns by name.
    Falls back to fixed column positions if detection fails.
    """
    path = Path(folder)
    if not path.exists():
        return None
    # Skip temporary Excel files (~$…)
    all_files = sorted([f for f in path.glob("*.xlsx") if not f.name.startswith("~$")])
    if not all_files:
        return None

    records = []
    for file in all_files:
        # Extract date from filename (e.g., 2026-05-09.xlsx)
        date_str = file.stem
        try:
            date = pd.to_datetime(date_str).date()
        except:
            continue   # skip files that can't be parsed as a date

        # Read the entire sheet without assuming a fixed layout
        df_raw = pd.read_excel(file, header=None)

        # Find the row that contains the word "BANK" (header row)
        header_row_idx = None
        for i, row in df_raw.iterrows():
            if any(str(val).strip().upper() == "BANK" for val in row if pd.notna(val)):
                header_row_idx = i
                break
        if header_row_idx is None:
            # Fallback: assume data starts at row 7 (0‑based index 6)
            header_row_idx = 6

        # Use that row as column headers (convert to uppercase for matching)
        raw_headers = df_raw.iloc[header_row_idx].fillna("").astype(str).str.strip().str.upper()

        # Extract data rows (everything after the header)
        df_day = df_raw.iloc[header_row_idx + 1 :].copy()
        df_day.columns = raw_headers

        # Helper to find a column containing ALL given keywords
        def find_col(keywords):
            for col in df_day.columns:
                if all(k in col for k in keywords):
                    return col
            return None

        # Try to identify columns by expected keywords
        bank_col = find_col(["BANK"])
        in_txn_col = find_col(["DESTINATION", "TRANSACTION"]) or find_col(["NO", "TRANSACTIONS"])
        in_val_col = find_col(["DESTINATION", "VALUES"])
        out_txn_col = find_col(["SOURCE", "TRANSACTION"])
        out_val_col = find_col(["SOURCE", "VALUES"])

        # If any column not found, fall back to the original fixed positions (indices 1‑5)
        if not all([bank_col, in_txn_col, in_val_col, out_txn_col, out_val_col]):
            df_day = df_raw.iloc[header_row_idx + 1 :, [1, 2, 3, 4, 5]]
            df_day.columns = ["Bank", "Inbound Txns", "Inbound Value", "Outbound Txns", "Outbound Value"]
        else:
            df_day = df_day[[bank_col, in_txn_col, in_val_col, out_txn_col, out_val_col]]
            df_day.columns = ["Bank", "Inbound Txns", "Inbound Value", "Outbound Txns", "Outbound Value"]

        # Clean the data
        df_day = df_day.dropna(subset=["Bank"])
        # Ensure Bank column is string
        if not pd.api.types.is_string_dtype(df_day["Bank"]):
            df_day["Bank"] = df_day["Bank"].astype(str)
        # Remove the TOTAL row
        df_day = df_day[~df_day["Bank"].str.strip().str.upper().str.contains("TOTAL")]

        df_day["Date"] = date
        records.append(df_day)

    if not records:
        return None

    df = pd.concat(records, ignore_index=True)
    # Convert numeric columns
    for col in ["Inbound Value", "Outbound Value", "Inbound Txns", "Outbound Txns"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["Total Value"] = df["Inbound Value"] + df["Outbound Value"]
    df["Net Flow"] = df["Inbound Value"] - df["Outbound Value"]
    return df

# Load IPS data (mandatory)
df_ips = load_all_data("data")
if df_ips is None or df_ips.empty:
    st.error("No valid IPS data files found in 'data/' folder. Please add Excel files.")
    st.stop()

# Load QR data (optional)
df_qr = load_all_data("data_qr")

# ========== SIDEBAR CONTROLS ==========
st.sidebar.title("💳 EthSwitch Dashboard")

# Data source selector (IPS / QR) – appears only if QR folder exists with files
data_sources = ["IPS"]
if df_qr is not None and not df_qr.empty:
    data_sources.append("QR")
data_source = st.sidebar.radio("📂 Data Source", data_sources, horizontal=True)

# Active dataframe
df_active = df_ips if data_source == "IPS" else df_qr
dates_list = sorted(df_active["Date"].unique())

# View mode
view_mode = st.sidebar.radio(
    "🔍 Select View",
    ["Single Date", "All Days Summary", "Date Range"]
)

# Dashen Bank guarantee
force_dashen = st.sidebar.checkbox("Always include Dashen Bank in Top 10", value=True)

# ========== VIEW LOGIC ==========
if view_mode == "Single Date":
    selected_date = st.sidebar.selectbox("Pick a date", dates_list, index=len(dates_list)-1)
    df_view = df_active[df_active["Date"] == selected_date].copy()
    title_suffix = f" – {selected_date}"
    daily_data_for_trends = None

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
    daily_data_for_trends = None

elif view_mode == "Date Range":
    min_date = min(dates_list)
    max_date = max(dates_list)
    start_date, end_date = st.sidebar.date_input(
        "Select date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )
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
    daily_data_for_trends = df_range.copy()

# Common calculations
df_view["Market Share (%)"] = (df_view["Total Value"] / df_view["Total Value"].sum()) * 100
top10 = df_view.nlargest(10, "Total Value")

# Force Dashen into top 10 if requested and not already present
if force_dashen and "Dashen" not in top10["Bank"].values:
    dashen_row = df_view[df_view["Bank"] == "Dashen"]
    if not dashen_row.empty:
        top10 = pd.concat([top10.iloc[:-1], dashen_row])
        top10 = top10.sort_values("Total Value", ascending=False)

# ========== PAGE SELECTION ==========
page = st.sidebar.radio(
    "📊 Navigate",
    ["Overview", "Market Share", "Value Flows", "Transaction Volumes",
     "Net Flows", "All-in-One View", "Trends"]
)

st.title(f"💳 EthSwitch {data_source} Dashboard{title_suffix}")

# ========== HELPER ==========
def styled_bar(x, y, title, xlabel, color=None, text_format=None):
    fig = go.Figure(go.Bar(
        x=x, y=y, orientation='h',
        text=text_format(x) if text_format else x,
        textposition='outside',
        marker_color=color or '#4682B4',
        hovertemplate='%{y}: %{x}<extra></extra>'
    ))
    fig.update_layout(title=title, xaxis_title=xlabel,
                      template='plotly_white', height=500,
                      margin=dict(l=160, r=50, t=50, b=40))
    return fig

# ========== PAGES ==========
if page == "Overview":
    st.header("📌 System Overview")
    total_val_bn = df_view['Total Value'].sum() / 1e9
    total_txns = (df_view['Inbound Txns'] + df_view['Outbound Txns']).sum()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Value (B ETB)", f"{total_val_bn:.2f}")
    col2.metric("Total Transactions", f"{total_txns:,.0f}")
    col3.metric("Active Institutions", len(df_view))
    col4.metric("Top Bank (Value)", top10.iloc[0]['Bank'])

    st.subheader("Top 10 Banks by Total Value")
    x_vals = top10['Total Value'].iloc[::-1] / 1e6
    y_vals = top10['Bank'].iloc[::-1]
    fig = styled_bar(x=x_vals, y=y_vals,
                     title="Total Value (Million ETB)", xlabel="M ETB",
                     color='#3CB371', text_format=lambda x: [f"{v:,.1f}" for v in x])
    st.plotly_chart(fig, width='stretch')

elif page == "Market Share":
    st.header("🥧 Market Share")
    col1, col2 = st.columns([6, 4])
    with col1:
        other_share = 100 - top10['Market Share (%)'].sum()
        pie_df = pd.DataFrame({'Bank': list(top10['Bank']) + ['Others'],
                               'Share': list(top10['Market Share (%)']) + [other_share]})
        fig_pie = px.pie(pie_df, values='Share', names='Bank',
                         title="Market Share by Total Value (Top 10 + Others)",
                         color_discrete_sequence=px.colors.qualitative.Set2)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_pie, width='stretch')
    with col2:
        st.subheader("Top 10 Breakdown")
        st.dataframe(top10[['Bank', 'Market Share (%)']].style.format({"Market Share (%)": "{:.1f}%"}))

elif page == "Value Flows":
    st.header("💸 Inbound vs Outbound Value")
    fig = go.Figure()
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Value']/1e6,
                         name='Inbound', orientation='h', marker_color='#2E8B57'))
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Value']/1e6,
                         name='Outbound', orientation='h', marker_color='#CD5C5C'))
    fig.update_layout(barmode='group', title="Inbound vs Outbound Value (M ETB)",
                      template='plotly_white', height=500)
    st.plotly_chart(fig, width='stretch')

elif page == "Transaction Volumes":
    st.header("📈 Transaction Counts")
    fig = go.Figure()
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Txns'],
                         name='Inbound Txns', orientation='h', marker_color='#1E90FF'))
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Txns'],
                         name='Outbound Txns', orientation='h', marker_color='#FF8C00'))
    fig.update_layout(barmode='group', title="Transactions",
                      template='plotly_white', height=500)
    st.plotly_chart(fig, width='stretch')

elif page == "Net Flows":
    st.header("⚖️ Net Flow (Received – Sent)")
    net = top10['Net Flow'] / 1e6
    colors = ['#2E8B57' if v >= 0 else '#CD5C5C' for v in net]
    fig = go.Figure(go.Bar(x=net[::-1], y=top10['Bank'].iloc[::-1],
                           orientation='h', marker_color=colors[::-1],
                           text=[f"{v:+.1f} M" for v in net[::-1]],
                           textposition='outside'))
    fig.update_layout(title="Net Flow in Million ETB", template='plotly_white', height=500)
    st.plotly_chart(fig, width='stretch')

elif page == "All-in-One View":
    st.header("🗂️ Complete Dashboard View")
    st.subheader("Market Share")
    col1, col2 = st.columns(2)
    with col1:
        other_share = 100 - top10['Market Share (%)'].sum()
        pie_df = pd.DataFrame({'Bank': list(top10['Bank']) + ['Others'],
                               'Share': list(top10['Market Share (%)']) + [other_share]})
        fig_pie = px.pie(pie_df, values='Share', names='Bank',
                         title="Market Share", color_discrete_sequence=px.colors.qualitative.Set2)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_pie.update_layout(height=350)
        st.plotly_chart(fig_pie, width='stretch')
    with col2:
        net = top10['Net Flow'] / 1e6
        colors = ['#2E8B57' if v >= 0 else '#CD5C5C' for v in net]
        fig_net = go.Figure(go.Bar(x=net[::-1], y=top10['Bank'].iloc[::-1],
                                   orientation='h', marker_color=colors[::-1],
                                   text=[f"{v:+.1f}" for v in net[::-1]],
                                   textposition='outside'))
        fig_net.update_layout(title="Net Flow (M ETB)", template='plotly_white', height=350)
        st.plotly_chart(fig_net, width='stretch')

    st.subheader("Value Comparison")
    fig_val = go.Figure()
    fig_val.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Value']/1e6,
                             name='Inbound', orientation='h', marker_color='#2E8B57'))
    fig_val.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Value']/1e6,
                             name='Outbound', orientation='h', marker_color='#CD5C5C'))
    fig_val.update_layout(barmode='group', title="Inbound vs Outbound Value (M ETB)",
                          template='plotly_white', height=400)
    st.plotly_chart(fig_val, width='stretch')

    st.subheader("Transaction Volumes")
    fig_txn = go.Figure()
    fig_txn.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Txns'],
                             name='Inbound Txns', orientation='h', marker_color='#1E90FF'))
    fig_txn.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Txns'],
                             name='Outbound Txns', orientation='h', marker_color='#FF8C00'))
    fig_txn.update_layout(barmode='group', title="Transactions", template='plotly_white', height=400)
    st.plotly_chart(fig_txn, width='stretch')

elif page == "Trends":
    st.header("📈 Daily Trends")
    if view_mode == "All Days Summary":
        st.info("Switch to 'Single Date' or 'Date Range' view to see daily trends.")
    else:
        if view_mode == "Single Date":
            daily_data = df_active[df_active["Date"] == selected_date]
        else:  # Date Range
            daily_data = daily_data_for_trends

        daily_totals = daily_data.groupby("Date").agg(
            Total_Value=("Total Value", "sum"),
            In_Txns=("Inbound Txns", "sum"),
            Out_Txns=("Outbound Txns", "sum")
        ).reset_index()
        daily_totals["Total_Txns"] = daily_totals["In_Txns"] + daily_totals["Out_Txns"]

        # System total value over time
        fig1 = px.line(daily_totals, x="Date", y="Total_Value",
                       title="Daily Total Value (ETB)", markers=True)
        fig1.update_layout(template='plotly_white')
        st.plotly_chart(fig1, width='stretch')

        # Top 5 banks (by total in the period)
        top5_banks = daily_data.groupby("Bank")["Total Value"].sum().nlargest(5).index
        top5_trend = daily_data[daily_data["Bank"].isin(top5_banks)].groupby(
            ["Date", "Bank"])["Total Value"].sum().reset_index()
        fig2 = px.line(top5_trend, x="Date", y="Total Value", color="Bank",
                       title="Top 5 Banks – Daily Total Value", markers=True)
        fig2.update_layout(template='plotly_white')
        st.plotly_chart(fig2, width='stretch')

        # Transaction counts
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=daily_totals["Date"], y=daily_totals["In_Txns"],
                                  name="Inbound Txns", mode="lines+markers"))
        fig4.add_trace(go.Scatter(x=daily_totals["Date"], y=daily_totals["Out_Txns"],
                                  name="Outbound Txns", mode="lines+markers"))
        fig4.update_layout(title="Daily Transaction Counts", template='plotly_white')
        st.plotly_chart(fig4, width='stretch')

# ========== FOOTER ==========
st.sidebar.markdown("---")
st.sidebar.caption(f"Data: EthSwitch {data_source}, {len(dates_list)} days")