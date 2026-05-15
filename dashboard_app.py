import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from pathlib import Path

# ========== CONFIG ==========
st.set_page_config(page_title="EthSwitch IPS Dashboard", layout="wide")
st.title("💳 EthSwitch IPS Dashboard")

# ========== LOAD & PREPARE DATA ==========
@st.cache_data
def load_all_data(folder="data"):
    all_files = sorted(Path(folder).glob("*.xlsx"))
    if not all_files:
        st.error(f"No .xlsx files found in '{folder}'. Please add files.")
        st.stop()

    records = []
    for file in all_files:
        date_str = file.stem
        date = pd.to_datetime(date_str).date()
        df_day = pd.read_excel(file, header=None, skiprows=6)
        df_day = df_day.iloc[:, [1, 2, 3, 4, 5]]
        df_day.columns = ["Bank", "Inbound Txns", "Inbound Value",
                          "Outbound Txns", "Outbound Value"]
        df_day = df_day.dropna(subset=["Bank"])
        df_day = df_day[~df_day["Bank"].str.strip().str.upper().str.contains("TOTAL")]
        df_day["Date"] = date
        records.append(df_day)

    df = pd.concat(records, ignore_index=True)
    for col in ["Inbound Value", "Outbound Value", "Inbound Txns", "Outbound Txns"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["Total Value"] = df["Inbound Value"] + df["Outbound Value"]
    df["Net Flow"] = df["Inbound Value"] - df["Outbound Value"]
    return df

df_all = load_all_data("data")
dates_list = sorted(df_all["Date"].unique())
default_date = dates_list[-1]

# ========== SIDEBAR ==========
st.sidebar.header("⚙️ Settings")
view_mode = st.sidebar.radio(
    "Select View",
    ["Single Date", "All Days Summary", "Date Range"]
)

if view_mode == "Single Date":
    selected_date = st.sidebar.selectbox("Pick a date", dates_list, index=len(dates_list)-1)
    df_view = df_all[df_all["Date"] == selected_date].copy()
    title_suffix = f" – {selected_date}"
elif view_mode == "All Days Summary":
    # Aggregate all days
    df_view = df_all.groupby("Bank", as_index=False).agg({
        "Inbound Value": "sum",
        "Outbound Value": "sum",
        "Inbound Txns": "sum",
        "Outbound Txns": "sum",
        "Total Value": "sum",
        "Net Flow": "sum",
    })
    title_suffix = " – All Days Combined"
elif view_mode == "Date Range":
    min_date = min(dates_list)
    max_date = max(dates_list)
    start_date, end_date = st.sidebar.date_input(
        "Select date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )
    mask = (df_all["Date"] >= start_date) & (df_all["Date"] <= end_date)
    df_range = df_all[mask]
    # Aggregate across the selected range
    df_view = df_range.groupby("Bank", as_index=False).agg({
        "Inbound Value": "sum",
        "Outbound Value": "sum",
        "Inbound Txns": "sum",
        "Outbound Txns": "sum",
        "Total Value": "sum",
        "Net Flow": "sum",
    })
    title_suffix = f" – {start_date} to {end_date}"
    # Store filtered non-aggregated data for the Trends page (daily within range)
    daily_data_for_trends = df_range

df_view["Market Share (%)"] = (df_view["Total Value"] / df_view["Total Value"].sum()) * 100
top10 = df_view.nlargest(10, "Total Value")

# Page navigation
page = st.sidebar.radio(
    "📊 Navigate",
    ["Overview", "Market Share", "Value Flows", "Transaction Volumes",
     "Net Flows", "All-in-One View", "Trends"]
)

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
    st.header(f"📌 System Overview{title_suffix}")
    total_val_bn = df_view['Total Value'].sum() / 1e9
    total_txns = (df_view['Inbound Txns'] + df_view['Outbound Txns']).sum()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Value (B ETB)", f"{total_val_bn:.2f}")
    col2.metric("Total Transactions", f"{total_txns:,.0f}")
    col3.metric("Active Institutions", len(df_view))
    col4.metric("Top Bank (Value)", top10.iloc[0]['Bank'])

    st.subheader("Top 10 Banks by Total Value")
    # FIXED: reverse both x and y for correct alignment
    x_vals = top10['Total Value'].iloc[::-1] / 1e6
    y_vals = top10['Bank'].iloc[::-1]
    fig = styled_bar(x=x_vals, y=y_vals,
                     title="Total Value (Million ETB)", xlabel="M ETB",
                     color='#3CB371', text_format=lambda x: [f"{v:,.1f}" for v in x])
    st.plotly_chart(fig, use_container_width=True)

elif page == "Market Share":
    st.header(f"🥧 Market Share{title_suffix}")
    col1, col2 = st.columns([6, 4])
    with col1:
        other_share = 100 - top10['Market Share (%)'].sum()
        pie_df = pd.DataFrame({'Bank': list(top10['Bank']) + ['Others'],
                               'Share': list(top10['Market Share (%)']) + [other_share]})
        fig_pie = px.pie(pie_df, values='Share', names='Bank',
                         title="Market Share by Total Value (Top 10 + Others)",
                         color_discrete_sequence=px.colors.qualitative.Set2)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)
    with col2:
        st.subheader("Top 10 Breakdown")
        st.dataframe(top10[['Bank', 'Market Share (%)']].style.format({"Market Share (%)": "{:.1f}%"}))

elif page == "Value Flows":
    st.header(f"💸 Inbound vs Outbound Value{title_suffix}")
    fig = go.Figure()
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Value']/1e6,
                         name='Inbound', orientation='h', marker_color='#2E8B57'))
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Value']/1e6,
                         name='Outbound', orientation='h', marker_color='#CD5C5C'))
    fig.update_layout(barmode='group', title="Inbound vs Outbound Value (M ETB)",
                      template='plotly_white', height=500)
    st.plotly_chart(fig, use_container_width=True)

elif page == "Transaction Volumes":
    st.header(f"📈 Transaction Counts{title_suffix}")
    fig = go.Figure()
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Txns'],
                         name='Inbound Txns', orientation='h', marker_color='#1E90FF'))
    fig.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Txns'],
                         name='Outbound Txns', orientation='h', marker_color='#FF8C00'))
    fig.update_layout(barmode='group', title="Transactions",
                      template='plotly_white', height=500)
    st.plotly_chart(fig, use_container_width=True)

elif page == "Net Flows":
    st.header(f"⚖️ Net Flow (Received – Sent){title_suffix}")
    net = top10['Net Flow'] / 1e6
    colors = ['#2E8B57' if v >= 0 else '#CD5C5C' for v in net]
    fig = go.Figure(go.Bar(x=net[::-1], y=top10['Bank'].iloc[::-1],
                           orientation='h', marker_color=colors[::-1],
                           text=[f"{v:+.1f} M" for v in net[::-1]],
                           textposition='outside'))
    fig.update_layout(title="Net Flow in Million ETB", template='plotly_white', height=500)
    st.plotly_chart(fig, use_container_width=True)

elif page == "All-in-One View":
    st.header(f"🗂️ Complete Dashboard{title_suffix}")
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
        st.plotly_chart(fig_pie, use_container_width=True)
    with col2:
        net = top10['Net Flow'] / 1e6
        colors = ['#2E8B57' if v >= 0 else '#CD5C5C' for v in net]
        fig_net = go.Figure(go.Bar(x=net[::-1], y=top10['Bank'].iloc[::-1],
                                   orientation='h', marker_color=colors[::-1],
                                   text=[f"{v:+.1f}" for v in net[::-1]],
                                   textposition='outside'))
        fig_net.update_layout(title="Net Flow (M ETB)", template='plotly_white', height=350)
        st.plotly_chart(fig_net, use_container_width=True)

    st.subheader("Value Comparison")
    fig_val = go.Figure()
    fig_val.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Value']/1e6,
                             name='Inbound', orientation='h', marker_color='#2E8B57'))
    fig_val.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Value']/1e6,
                             name='Outbound', orientation='h', marker_color='#CD5C5C'))
    fig_val.update_layout(barmode='group', title="Inbound vs Outbound Value (M ETB)",
                          template='plotly_white', height=400)
    st.plotly_chart(fig_val, use_container_width=True)

    st.subheader("Transaction Volumes")
    fig_txn = go.Figure()
    fig_txn.add_trace(go.Bar(y=top10['Bank'], x=top10['Inbound Txns'],
                             name='Inbound Txns', orientation='h', marker_color='#1E90FF'))
    fig_txn.add_trace(go.Bar(y=top10['Bank'], x=top10['Outbound Txns'],
                             name='Outbound Txns', orientation='h', marker_color='#FF8C00'))
    fig_txn.update_layout(barmode='group', title="Transactions", template='plotly_white', height=400)
    st.plotly_chart(fig_txn, use_container_width=True)

elif page == "Trends":
    st.header("📈 Daily Trends (All Banks)")
    if view_mode == "All Days Summary":
        st.info("Switch to 'Single Date' view to see daily trends.")
    else:
        daily_totals = df_all.groupby("Date").agg(
            Total_Value=("Total Value", "sum"),
            In_Txns=("Inbound Txns", "sum"),
            Out_Txns=("Outbound Txns", "sum")
        ).reset_index()
        daily_totals["Total_Txns"] = daily_totals["In_Txns"] + daily_totals["Out_Txns"]

        fig1 = px.line(daily_totals, x="Date", y="Total_Value",
                       title="Daily Total Value (ETB)", markers=True)
        fig1.update_layout(template='plotly_white')
        st.plotly_chart(fig1, use_container_width=True)

        # Top 5 banks overall (by total across all days)
        top5_banks = df_all.groupby("Bank")["Total Value"].sum().nlargest(5).index
        top5_trend = df_all[df_all["Bank"].isin(top5_banks)].groupby(
            ["Date", "Bank"])["Total Value"].sum().reset_index()
        fig2 = px.line(top5_trend, x="Date", y="Total Value", color="Bank",
                       title="Top 5 Banks – Daily Total Value", markers=True)
        fig2.update_layout(template='plotly_white')
        st.plotly_chart(fig2, use_container_width=True)

        # Transaction counts
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=daily_totals["Date"], y=daily_totals["In_Txns"],
                                  name="Inbound Txns", mode="lines+markers"))
        fig4.add_trace(go.Scatter(x=daily_totals["Date"], y=daily_totals["Out_Txns"],
                                  name="Outbound Txns", mode="lines+markers"))
        fig4.update_layout(title="Daily Transaction Counts", template='plotly_white')
        st.plotly_chart(fig4, use_container_width=True)

# ========== FOOTER ==========
st.sidebar.markdown("---")
st.sidebar.caption(f"Data: EthSwitch IPS, {len(dates_list)} days")