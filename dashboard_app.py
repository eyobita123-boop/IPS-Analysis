import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta
from scipy import stats
import io

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


# ========== ADVANCED METRICS FUNCTIONS ==========
def calculate_advanced_metrics(df_data, df_trend):
    """Calculate all advanced metrics (1, 2, 3, 4, 8, 9, 10, 12, 18)"""
    metrics = {}
    
    # #1: Average Transaction Value
    df_data["Avg Txn Value"] = (df_data["Total Value"] / (df_data["Inbound Txns"] + df_data["Outbound Txns"] + 1)).replace([np.inf, -np.inf], 0)
    
    # #2: Efficiency Ratio (Value per transaction)
    df_data["Efficiency Ratio"] = (df_data["Total Value"] / (df_data["Inbound Txns"] + df_data["Outbound Txns"] + 1)).replace([np.inf, -np.inf], 0)
    
    # #8: Herfindahl Index (Concentration)
    total_value = df_data["Total Value"].sum()
    if total_value > 0:
        market_shares = (df_data["Total Value"] / total_value) * 100
        herfindahl = (market_shares ** 2).sum()
    else:
        herfindahl = 0
    metrics["herfindahl"] = herfindahl
    
    # #18: Segment Analysis (Categorize banks)
    if len(df_data) > 0:
        q75 = df_data["Total Value"].quantile(0.75)
        q25 = df_data["Total Value"].quantile(0.25)
        df_data["Segment"] = df_data["Total Value"].apply(
            lambda x: "Large" if x >= q75 else ("Small" if x <= q25 else "Medium")
        )
    
    return df_data, metrics


def calculate_volatility(df_trend):
    """#4: Calculate volatility for each bank"""
    if df_trend.empty or "Date" not in df_trend.columns:
        return pd.DataFrame()
    
    volatility_data = []
    for bank in df_trend["Bank"].unique():
        bank_data = df_trend[df_trend["Bank"] == bank].sort_values("Date")
        if len(bank_data) > 1:
            daily_values = bank_data["Total Value"].values
            volatility = np.std(daily_values) / (np.mean(daily_values) + 1)
            volatility_data.append({"Bank": bank, "Volatility": volatility})
    
    return pd.DataFrame(volatility_data)


def calculate_wow_growth(df_trend):
    """#3: Calculate week-over-week growth"""
    if df_trend.empty or "Date" not in df_trend.columns:
        return pd.DataFrame()
    
    df_trend = df_trend.sort_values("Date").copy()
    wow_data = []
    
    for bank in df_trend["Bank"].unique():
        bank_data = df_trend[df_trend["Bank"] == bank].sort_values("Date")
        
        for i in range(7, len(bank_data)):
            current_week = bank_data.iloc[i]["Total Value"]
            previous_week = bank_data.iloc[i-7]["Total Value"]
            
            if previous_week != 0:
                growth = ((current_week - previous_week) / previous_week) * 100
            else:
                growth = 0
            
            wow_data.append({
                "Bank": bank,
                "Date": bank_data.iloc[i]["Date"],
                "WoW Growth (%)": growth
            })
    
    return pd.DataFrame(wow_data)


def detect_anomalies(df_trend):
    """#11: Detect anomalies using Z-score method"""
    anomalies = []
    
    for bank in df_trend["Bank"].unique():
        bank_data = df_trend[df_trend["Bank"] == bank].sort_values("Date")
        if len(bank_data) > 2:
            values = bank_data["Total Value"].values
            z_scores = np.abs(stats.zscore(values))
            
            for idx, (date, value, z) in enumerate(zip(bank_data["Date"], values, z_scores)):
                if z > 2.5:  # Threshold for anomaly
                    anomalies.append({
                        "Bank": bank,
                        "Date": date,
                        "Value": value,
                        "Anomaly Score": z
                    })
    
    return pd.DataFrame(anomalies)


def forecast_trend(df_trend, days=7):
    """#16: Simple exponential smoothing forecast"""
    if df_trend.empty or len(df_trend) < 3:
        return None
    
    daily = df_trend.groupby("Date")["Total Value"].sum().sort_index()
    
    if len(daily) < 2:
        return None
    
    # Simple exponential smoothing
    alpha = 0.3
    forecast = [daily.iloc[-1]]
    
    for _ in range(days):
        next_val = alpha * daily.iloc[-1] + (1 - alpha) * forecast[-1]
        forecast.append(next_val)
    
    future_dates = [daily.index[-1] + timedelta(days=i+1) for i in range(days)]
    return pd.DataFrame({
        "Date": future_dates,
        "Forecast": forecast[1:]
    })


def calculate_data_quality(df):
    """#14: Calculate data quality metrics"""
    quality = {
        "Total Records": len(df),
        "Missing Values": df.isnull().sum().sum(),
        "Duplicates": df.duplicated().sum(),
        "Zero Values": (df[["Inbound Value", "Outbound Value"]] == 0).sum().sum(),
        "Negative Values": (df[["Inbound Value", "Outbound Value"]] < 0).sum().sum(),
    }
    return quality


def detect_outliers_iqr(df, column):
    """Detect outliers using IQR method"""
    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1
    outliers = df[(df[column] < (Q1 - 1.5 * IQR)) | (df[column] > (Q3 + 1.5 * IQR))]
    return outliers


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

# Calculate advanced metrics
df_view, adv_metrics = calculate_advanced_metrics(df_view.copy(), trend_data)

top10 = df_view.nlargest(10, "Total Value").copy()
if force_dashen and "Dashen" not in top10["Bank"].values:
    dashen_row = df_view[df_view["Bank"] == "Dashen"]
    if not dashen_row.empty:
        top10 = pd.concat([top10.iloc[:-1], dashen_row])
        top10 = top10.sort_values("Total Value", ascending=False)

# Calculate additional analytics
volatility_df = calculate_volatility(trend_data)
wow_growth_df = calculate_wow_growth(trend_data)
anomaly_df = detect_anomalies(trend_data)
forecast_df = forecast_trend(trend_data, days=7)
data_quality = calculate_data_quality(df_active)

# ========== PAGE SELECTION ==========
page = st.sidebar.radio(
    "📊 Navigate",
    [
        "Overview", "Market Share", "Value Flows", "Transaction Volumes", "Net Flows", "Trends",
        "Advanced Metrics", "Performance Analytics", "Bank Insights", "Anomalies & Alerts",
        "Forecasting", "Benchmarking", "Data Quality", "Multi-Source Compare", "Custom Builder",
        "Segment Analysis", "Data Explorer", "Export"
    ]
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

# ========== NEW ADVANCED PAGES ==========
elif page == "Advanced Metrics":
    st.header("📊 Advanced Metrics & Ratios")
    st.markdown("### Efficiency Analysis (#1, #2, #8)")
    
    if top10.empty:
        st.warning("No data available.")
    else:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Herfindahl Index", f"{adv_metrics['herfindahl']:.0f}", 
                     help="Market concentration (0-10000). Higher = more concentrated")
        
        with col2:
            avg_efficiency = df_view["Efficiency Ratio"].mean()
            st.metric("Avg Efficiency", f"{format_etb(avg_efficiency, scale=1e6)} ETB/Txn")
        
        with col3:
            avg_txn = df_view["Avg Txn Value"].mean()
            st.metric("Avg Transaction", f"{format_etb(avg_txn, scale=1e6)} ETB")
        
        st.markdown("---")
        st.subheader("Efficiency Ratio by Bank (Top 10)")
        
        eff_fig = styled_bar(
            x=top10["Efficiency Ratio"].iloc[::-1] / 1e6,
            y=top10["Bank"].iloc[::-1],
            title="Efficiency Ratio (Value per Transaction)",
            xlabel="Million ETB",
            color="#FF9800"
        )
        st.plotly_chart(eff_fig, use_container_width=True)
        
        st.markdown("---")
        st.subheader("Efficiency Metrics Table")
        eff_table = top10[["Bank", "Avg Txn Value", "Efficiency Ratio", "Total Value", "Inbound Txns", "Outbound Txns"]].copy()
        st.dataframe(eff_table.style.format({
            "Avg Txn Value": "{:,.0f}",
            "Efficiency Ratio": "{:,.0f}",
            "Total Value": "{:,.0f}",
            "Inbound Txns": "{:,.0f}",
            "Outbound Txns": "{:,.0f}"
        }))

elif page == "Performance Analytics":
    st.header("📈 Performance Analytics (#3, #4, #12)")
    
    st.markdown("### Week-over-Week Growth")
    if not wow_growth_df.empty:
        wow_pivot = wow_growth_df.pivot_table(index="Date", columns="Bank", values="WoW Growth (%)", aggfunc="first")
        fig = px.line(
            wow_growth_df.sort_values("Date"),
            x="Date",
            y="WoW Growth (%)",
            color="Bank",
            title="Week-over-Week Growth Rate (%)",
            markers=True
        )
        fig.update_layout(template='plotly_white', height=500)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data for WoW analysis (need at least 8 days).")
    
    st.markdown("---")
    st.markdown("### Volatility Analysis")
    if not volatility_df.empty:
        vol_fig = styled_bar(
            x=volatility_df.sort_values("Volatility", ascending=True)["Volatility"].iloc[::-1],
            y=volatility_df.sort_values("Volatility", ascending=True)["Bank"].iloc[::-1],
            title="Bank Volatility (Lower = More Stable)",
            xlabel="Volatility Score",
            color="#9C27B0"
        )
        st.plotly_chart(vol_fig, use_container_width=True)
        st.dataframe(volatility_df.sort_values("Volatility", ascending=False).style.format({"Volatility": "{:.4f}"}))
    else:
        st.info("Not enough data for volatility analysis.")
    
    st.markdown("---")
    st.markdown("### Peer Benchmarking")
    if len(df_view) > 1:
        avg_value = df_view["Total Value"].mean()
        df_view["vs_Average"] = ((df_view["Total Value"] - avg_value) / avg_value) * 100
        bench_df = df_view[["Bank", "Total Value", "vs_Average"]].sort_values("vs_Average", ascending=False)
        
        fig = px.bar(
            bench_df,
            x="vs_Average",
            y="Bank",
            orientation="h",
            color="vs_Average",
            color_continuous_scale=["#CD5C5C", "#FFFFFF", "#2E8B57"],
            title="Performance vs Average Bank",
            labels={"vs_Average": "% vs Average"}
        )
        st.plotly_chart(fig, use_container_width=True)

elif page == "Bank Insights":
    st.header("🏦 Individual Bank Drill-Down (#6)")
    
    selected_bank = st.selectbox("Select a bank to analyze", df_view["Bank"].unique())
    
    if selected_bank:
        bank_data = trend_data[trend_data["Bank"] == selected_bank].sort_values("Date")
        
        if not bank_data.empty:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Value", f"{format_etb(bank_data['Total Value'].sum(), scale=1e9)} B")
            with col2:
                st.metric("Avg Daily", f"{format_etb(bank_data['Total Value'].mean(), scale=1e6)} M")
            with col3:
                st.metric("Peak Day", f"{format_etb(bank_data['Total Value'].max(), scale=1e6)} M")
            with col4:
                st.metric("Total Txns", f"{bank_data['Inbound Txns'].sum() + bank_data['Outbound Txns'].sum():,.0f}")
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Daily Trend")
                fig = px.line(bank_data, x="Date", y="Total Value", markers=True, title=f"{selected_bank} - Daily Total Value")
                fig.update_layout(template='plotly_white')
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                st.subheader("Inbound vs Outbound")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=bank_data["Date"], y=bank_data["Inbound Value"], name="Inbound", mode="lines+markers"))
                fig.add_trace(go.Scatter(x=bank_data["Date"], y=bank_data["Outbound Value"], name="Outbound", mode="lines+markers"))
                fig.update_layout(template='plotly_white', title=f"{selected_bank} - Flow Comparison")
                st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("---")
            st.subheader("Distribution Analysis (#7)")
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig = go.Figure(data=[go.Box(y=bank_data["Total Value"], name=selected_bank, marker_color="#3498db")])
                fig.update_layout(title="Distribution of Daily Values", template='plotly_white')
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.histogram(bank_data, x="Total Value", nbins=20, title="Histogram of Daily Values", color_discrete_sequence=["#3498db"])
                fig.update_layout(template='plotly_white')
                st.plotly_chart(fig, use_container_width=True)

elif page == "Anomalies & Alerts":
    st.header("🚨 Anomalies & Alerts (#10, #11)")
    
    st.markdown("### KPI Alert System")
    
    col1, col2 = st.columns(2)
    with col1:
        alert_threshold = st.slider("Alert Threshold (% from mean)", 0, 100, 20)
    with col2:
        anomaly_sensitivity = st.slider("Anomaly Sensitivity (Z-score)", 1.0, 3.5, 2.5, 0.1)
    
    # KPI Alerts
    st.subheader("Performance Alerts")
    if len(df_view) > 0:
        mean_value = df_view["Total Value"].mean()
        threshold_val = (alert_threshold / 100) * mean_value
        
        alerts = []
        for idx, row in df_view.iterrows():
            if row["Total Value"] < (mean_value - threshold_val):
                alerts.append({"Bank": row["Bank"], "Alert": "⚠️ Below Average", "Value": row["Total Value"]})
            elif row["Total Value"] > (mean_value + threshold_val):
                alerts.append({"Bank": row["Bank"], "Alert": "✅ Above Average", "Value": row["Total Value"]})
        
        if alerts:
            alerts_df = pd.DataFrame(alerts)
            st.dataframe(alerts_df)
        else:
            st.info("No alerts triggered.")
    
    st.markdown("---")
    st.subheader("Detected Anomalies")
    if not anomaly_df.empty:
        anomaly_filtered = anomaly_df[anomaly_df["Anomaly Score"] >= anomaly_sensitivity]
        if not anomaly_filtered.empty:
            st.dataframe(anomaly_filtered.sort_values("Anomaly Score", ascending=False))
        else:
            st.info(f"No anomalies detected at sensitivity level {anomaly_sensitivity}")
    else:
        st.info("No anomalies detected.")

elif page == "Forecasting":
    st.header("🔮 Forecasting & Predictions (#16)")
    
    st.markdown("### 7-Day Forecast")
    
    if forecast_df is not None and not forecast_df.empty:
        # Combine historical with forecast
        daily_actual = trend_data.groupby("Date")["Total Value"].sum().reset_index()
        daily_actual["Type"] = "Actual"
        daily_actual.columns = ["Date", "Value", "Type"]
        
        forecast_plot = forecast_df.copy()
        forecast_plot["Type"] = "Forecast"
        forecast_plot.columns = ["Date", "Value", "Type"]
        
        combined = pd.concat([daily_actual.tail(14), forecast_plot], ignore_index=True)
        
        fig = px.line(combined, x="Date", y="Value", color="Type", markers=True, title="Daily Value - Actual & Forecast")
        fig.update_layout(template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        st.subheader("Forecast Details")
        forecast_display = forecast_df.copy()
        forecast_display["Value"] = forecast_display["Value"].apply(lambda x: f"{format_etb(x, scale=1e6)} M")
        st.dataframe(forecast_display)
    else:
        st.info("Not enough data for forecasting (need at least 3 days).")

elif page == "Benchmarking":
    st.header("📊 Benchmarking Analysis (#12)")
    
    st.markdown("### Market Position Analysis")
    
    if len(df_view) > 1:
        avg_value = df_view["Total Value"].mean()
        median_value = df_view["Total Value"].median()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Market Average", f"{format_etb(avg_value, scale=1e6)} M")
        with col2:
            st.metric("Market Median", f"{format_etb(median_value, scale=1e6)} M")
        with col3:
            st.metric("Market Std Dev", f"{format_etb(df_view['Total Value'].std(), scale=1e6)} M")
        
        st.markdown("---")
        
        # Benchmark chart
        df_view["Benchmark_Status"] = df_view["Total Value"].apply(
            lambda x: "Above Average" if x > avg_value else "Below Average"
        )
        
        fig = px.scatter(
            df_view.sort_values("Total Value", ascending=False).head(20),
            x="Bank",
            y="Total Value",
            color="Benchmark_Status",
            color_discrete_map={"Above Average": "#2E8B57", "Below Average": "#CD5C5C"},
            title="Bank Benchmark vs Market Average",
            hover_data=["Market Share (%)"]
        )
        fig.add_hline(y=avg_value, line_dash="dash", line_color="gray", annotation_text="Average")
        st.plotly_chart(fig, use_container_width=True)

elif page == "Data Quality":
    st.header("📋 Data Quality Report (#14)")
    
    st.markdown("### Overall Data Quality")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Records", data_quality["Total Records"])
    with col2:
        st.metric("Missing Values", data_quality["Missing Values"])
    with col3:
        st.metric("Duplicates", data_quality["Duplicates"])
    with col4:
        st.metric("Zero Values", data_quality["Zero Values"])
    with col5:
        st.metric("Negative Values", data_quality["Negative Values"])
    
    st.markdown("---")
    st.markdown("### Outliers Detection")
    
    outliers_inbound = detect_outliers_iqr(df_active, "Inbound Value")
    outliers_outbound = detect_outliers_iqr(df_active, "Outbound Value")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Inbound Outliers", len(outliers_inbound))
    with col2:
        st.metric("Outbound Outliers", len(outliers_outbound))
    
    if not outliers_inbound.empty or not outliers_outbound.empty:
        st.subheader("Top Outlier Records")
        all_outliers = pd.concat([outliers_inbound, outliers_outbound]).drop_duplicates().nlargest(10, "Total Value")
        st.dataframe(all_outliers[["Bank", "Date", "Inbound Value", "Outbound Value", "Total Value"]])

elif page == "Multi-Source Compare":
    st.header("🔄 Multi-Source Comparison (#15)")
    
    if len(all_data_sources) > 1:
        sources_to_compare = st.multiselect("Select sources to compare", list(all_data_sources.keys()), 
                                            default=list(all_data_sources.keys())[:2])
        
        comparison_data = []
        for source in sources_to_compare:
            df_source = all_data_sources[source]
            comparison_data.append({
                "Source": source,
                "Total Value": df_source["Total Value"].sum(),
                "Total Txns": df_source["Inbound Txns"].sum() + df_source["Outbound Txns"].sum(),
                "Banks": df_source["Bank"].nunique(),
                "Date Range": f"{df_source['Date'].min()} to {df_source['Date'].max()}"
            })
        
        comp_df = pd.DataFrame(comparison_data)
        
        col1, col2 = st.columns(2)
        
        with col1:
            fig = px.bar(comp_df, x="Source", y="Total Value", title="Total Value by Source", color="Source")
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            fig = px.bar(comp_df, x="Source", y="Total Txns", title="Total Transactions by Source", color="Source")
            st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(comp_df)
    else:
        st.info("Need at least 2 data sources for comparison.")

elif page == "Custom Builder":
    st.header("🔧 Custom Metrics Builder (#17)")
    
    st.markdown("### Create Custom Metrics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        metric_name = st.text_input("Metric Name", "My Metric")
        numerator = st.selectbox("Numerator", ["Total Value", "Inbound Value", "Outbound Value", "Inbound Txns", "Outbound Txns"])
    
    with col2:
        denominator = st.selectbox("Denominator", ["Total Value", "Inbound Value", "Outbound Value", "Inbound Txns", "Outbound Txns"])
        scale = st.selectbox("Scale", ["1", "1M", "1B"])
    
    if st.button("Calculate Metric"):
        scale_map = {"1": 1, "1M": 1e6, "1B": 1e9}
        if df_view[denominator].sum() != 0:
            custom_metric = (df_view[numerator] / df_view[denominator]) / scale_map[scale]
            df_view[metric_name] = custom_metric
            
            fig = styled_bar(
                x=df_view[metric_name].iloc[::-1],
                y=df_view["Bank"].iloc[::-1],
                title=f"{metric_name}: {numerator} / {denominator}",
                xlabel=metric_name,
                color="#00BCD4"
            )
            st.plotly_chart(fig, use_container_width=True)

elif page == "Segment Analysis":
    st.header("🎯 Bank Segment Analysis (#18)")
    
    st.markdown("### Market Segmentation")
    
    if "Segment" in df_view.columns:
        segment_summary = df_view.groupby("Segment").agg({
            "Total Value": ["sum", "mean", "count"],
            "Market Share (%)": "sum"
        }).round(2)
        
        col1, col2, col3 = st.columns(3)
        
        for idx, segment in enumerate(["Large", "Medium", "Small"]):
            segment_data = df_view[df_view["Segment"] == segment]
            if not segment_data.empty:
                if idx == 0:
                    with col1:
                        st.metric(f"{segment} Banks", len(segment_data), f"Value: {format_etb(segment_data['Total Value'].sum(), scale=1e6)} M")
                elif idx == 1:
                    with col2:
                        st.metric(f"{segment} Banks", len(segment_data), f"Value: {format_etb(segment_data['Total Value'].sum(), scale=1e6)} M")
                else:
                    with col3:
                        st.metric(f"{segment} Banks", len(segment_data), f"Value: {format_etb(segment_data['Total Value'].sum(), scale=1e6)} M")
        
        st.markdown("---")
        
        # Segment pie chart
        segment_pie = df_view.groupby("Segment")["Total Value"].sum()
        fig = px.pie(
            values=segment_pie.values,
            names=segment_pie.index,
            title="Market Share by Segment",
            color_discrete_map={"Large": "#D32F2F", "Medium": "#F57C00", "Small": "#388E3C"}
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Segment details
        st.subheader("Segment Details")
        for segment in ["Large", "Medium", "Small"]:
            with st.expander(f"{segment} Banks"):
                segment_banks = df_view[df_view["Segment"] == segment].sort_values("Total Value", ascending=False)
                st.dataframe(segment_banks[["Bank", "Total Value", "Market Share (%)", "Avg Txn Value"]])

elif page == "Data Explorer":
    st.header("🗃️ Data Explorer")
    st.markdown("Use the data explorer to inspect the filtered bank-level results.")
    if df_view.empty:
        st.warning("No records to display for the selected filters.")
    else:
        df_display = df_view.sort_values("Total Value", ascending=False).reset_index(drop=True)
        df_display["Market Share (%)"] = df_display["Market Share (%)"].round(2)
        st.dataframe(df_display)

elif page == "Export":
    st.header("💾 Export Data (#13)")
    
    st.markdown("### Download Your Analysis")
    
    export_options = st.multiselect(
        "Select data to export",
        ["Top 10 Banks", "All Banks", "Daily Trends", "Forecast", "Anomalies", "Volatility Analysis"],
        default=["Top 10 Banks", "All Banks"]
    )
    
    if st.button("Prepare Export"):
        with io.BytesIO() as excel_file:
            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
                if "Top 10 Banks" in export_options:
                    top10.to_excel(writer, sheet_name="Top 10 Banks", index=False)
                if "All Banks" in export_options:
                    df_view.to_excel(writer, sheet_name="All Banks", index=False)
                if "Daily Trends" in export_options and not trend_data.empty:
                    trend_data.to_excel(writer, sheet_name="Daily Trends", index=False)
                if "Forecast" in export_options and forecast_df is not None:
                    forecast_df.to_excel(writer, sheet_name="Forecast", index=False)
                if "Anomalies" in export_options and not anomaly_df.empty:
                    anomaly_df.to_excel(writer, sheet_name="Anomalies", index=False)
                if "Volatility Analysis" in export_options and not volatility_df.empty:
                    volatility_df.to_excel(writer, sheet_name="Volatility", index=False)
            
            excel_file.seek(0)
            st.download_button(
                label="📥 Download Excel Report",
                data=excel_file.getvalue(),
                file_name=f"ETH_Analysis_{data_source}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ========== FOOTER ==========
st.sidebar.markdown("---")
st.sidebar.caption(f"Source: {data_source} — {len(dates_list)} days, {bank_count} banks")
st.sidebar.caption("Dashboard by Eyob Dereje — [LinkedIn](https://www.linkedin.com/in/eyobderejebekele-bb8a02379)")

