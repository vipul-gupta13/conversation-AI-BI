import streamlit as st
import pandas as pd
import plotly.express as px
from openai import OpenAI
import os
import time
import json
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Superstore BI LLM Showdown",
    page_icon="🦙",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🦙 Superstore BI – Llama vs GPT-OSS (Groq)")
st.caption("Same data • Same prompt • Two different LLMs → Instant side-by-side BI dashboards")

# ====================== DATA ======================
@st.cache_data
def load_data():
    url = "https://gist.githubusercontent.com/nnbphuong/38db511db14542f3ba9ef16e69d3814c/raw/Superstore.csv"
    df = pd.read_csv(url)
    df['Order Date'] = pd.to_datetime(df['Order Date'])
    df['Ship Date'] = pd.to_datetime(df['Ship Date'])
    return df

df = load_data()

# ====================== METADATA (same for both LLMs) ======================
COLUMNS = df.columns.tolist()
METADATA = f"""
Dataset: Superstore Sales (US retail 2014-2017)
Rows: {len(df):,}
**Pre-computed global totals (use these EXACT values when relevant):**
- Total Sales (SUM(Sales)): {df['Sales'].sum():,.0f}
- Total Profit (SUM(Profit)): {df['Profit'].sum():,.0f}
Columns (use EXACT names only): {COLUMNS}
Numeric columns: Sales, Quantity, Discount, Profit
Date column: Order Date
Business context: Fictional US superstore selling Furniture, Office Supplies, Technology.
Goal: Help improve profitability, sales trends, regional performance.
"""

# ====================== PROMPT & SCHEMA ======================
SYSTEM_PROMPT = """You are an expert Business Intelligence Analyst.
You will be given the Superstore dataset above.
Always use EXACT column names from the metadata.
Never invent columns.
**CRITICAL: Do NOT make up or guess numeric totals/aggregates (Sales, Profit sums, etc.) unless the exact pre-computed value is explicitly provided in the metadata. If not provided, set the value to "Requires calculation – see charts" or omit the KPI.**

Respond ONLY with valid JSON (no markdown, no extra text) matching this exact schema:

{
  "dashboard_title": "string",
  "key_insight": "1-2 sentence actionable insight",
  "kpi_cards": [
    {"title": "string", "value": "string or number", "delta": "optional string e.g. +12%"}
  ],
  "charts": [
    {
      "chart_title": "string",
      "chart_type": "bar|line|pie|scatter",
      "x": "exact column name",
      "y": "exact column name",
      "color": "exact column name or null",
      "agg": "sum|mean|count|none"
    }
  ]
}
"""

JSON_SCHEMA = {
    "type": "json_object"
}

# ====================== GROQ CLIENT ======================
if "GROQ_API_KEY" in st.secrets:
    groq_key = st.secrets["GROQ_API_KEY"]
else:
    groq_key = os.getenv("GROQ_API_KEY")

if not groq_key:
    st.error("🔑 Please set your GROQ_API_KEY in .env (local) or Streamlit Cloud Secrets.")
    st.stop()

client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")

MODEL1 = "llama-3.3-70b-versatile"
MODEL2 = "openai/gpt-oss-20b"

# ====================== RENDER CHART HELPER ======================
def render_chart(df, chart):
    try:
        x = chart.get("x")
        y = chart.get("y")
        color = chart.get("color")
        agg = chart.get("agg", "none")
        title = chart.get("chart_title", "Untitled Chart")

        if not x or not y or x not in df.columns or y not in df.columns:
            return None

        if agg in ["sum", "mean", "count"]:
            group_cols = [x]
            if color and color in df.columns and color != x:
                group_cols.append(color)

            if agg == "sum":
                grouped = df.groupby(group_cols, as_index=False)[y].sum()
            elif agg == "mean":
                grouped = df.groupby(group_cols, as_index=False)[y].mean()
            else:  # count
                grouped = df.groupby(group_cols, as_index=False).size().reset_index(name="count")
                y = "count"
            df_to_use = grouped
            y_col = y
        else:
            df_to_use = df
            y_col = y

        if chart["chart_type"] == "bar":
            fig = px.bar(df_to_use, x=x, y=y_col, color=color, title=title)
        elif chart["chart_type"] == "line":
            fig = px.line(df_to_use, x=x, y=y_col, color=color, title=title)
        elif chart["chart_type"] == "pie":
            fig = px.pie(df_to_use, names=x, values=y_col, title=title)
        elif chart["chart_type"] == "scatter":
            fig = px.scatter(df_to_use, x=x, y=y_col, color=color, title=title)
        else:
            fig = px.bar(df_to_use, x=x, y=y_col, title=title)

        return fig
    except Exception as e:
        st.error(f"Chart render failed: {str(e)[:120]}")
        return None

# ====================== UI ======================
st.sidebar.header("Configuration")
st.sidebar.info(f"""
**LLM 1**: {MODEL1} (Llama)  
**LLM 2**: {MODEL2} (Mixtral OSS)  
**Data**: Superstore Sales ({len(df):,} rows)
""")

query = st.text_area("Your BI Question", 
    "Show me total sales and profit by region and category. Also show monthly sales trend and top KPIs.",
    height=100)

if st.button("🚀 Generate Dashboards with Both LLMs", type="primary"):
    if not os.getenv("GROQ_API_KEY"):
        st.error("Please set GROQ_API_KEY in .env or environment")
        st.stop()

    full_prompt = f"{METADATA}\n\nUser Query: {query}\n\nReturn ONLY JSON."

    with st.spinner("Calling both LLMs in parallel..."):
        start = time.time()
        
        # Parallel calls
        response1 = client.chat.completions.create(
            model=MODEL1,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": full_prompt}],
            response_format=JSON_SCHEMA,
            temperature=0.0,
            max_tokens=1500
        )
        
        response2 = client.chat.completions.create(
            model=MODEL2,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": full_prompt}],
            response_format=JSON_SCHEMA,
            temperature=0.0,
            max_tokens=1500
        )
        
        latency = round(time.time() - start, 2)

    # Parse
    try:
        data1 = json.loads(response1.choices[0].message.content)
        data2 = json.loads(response2.choices[0].message.content)
    except:
        st.error("JSON parse failed – LLM did not follow schema")
        st.stop()

    # ====================== SIDE-BY-SIDE DISPLAY ======================
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader(f"🦙 {MODEL1}")
        st.write(f"**Key Insight**: {data1.get('key_insight', '')}")
        
        kpi_row = st.columns(len(data1.get("kpi_cards", [])) or 1)
        for i, kpi in enumerate(data1.get("kpi_cards", [])):
            with kpi_row[i]:
                st.metric(kpi["title"], kpi["value"], kpi.get("delta"))
        
        # for chart in data1.get("charts", []):
        #     fig = render_chart(df, chart)
        #     if fig:
        #         st.plotly_chart(fig, use_container_width=True)
        for i, chart in enumerate(data1.get("charts", [])):
            fig = render_chart(df, chart)
            if fig:
                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    key=f"llama_chart_{i}_{chart.get('chart_title','unnamed')}"   # ← unique key
                )
    
    with col2:
        st.subheader(f"🔀 {MODEL2}")
        st.write(f"**Key Insight**: {data2.get('key_insight', '')}")
        
        kpi_row = st.columns(len(data2.get("kpi_cards", [])) or 1)
        for i, kpi in enumerate(data2.get("kpi_cards", [])):
            with kpi_row[i]:
                st.metric(kpi["title"], kpi["value"], kpi.get("delta"))
        
        # for chart in data2.get("charts", []):
        #     fig = render_chart(df, chart)
        #     if fig:
        #         st.plotly_chart(fig, use_container_width=True)
        for i, chart in enumerate(data2.get("charts", [])):
            fig = render_chart(df, chart)
            if fig:
                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    key=f"mixtral_chart_{i}_{chart.get('chart_title','unnamed')}"   # ← unique key
                )

    # Comparison
    st.divider()
    st.subheader("📊 Comparison")
    st.write(f"**Total latency**: {latency}s")
    st.write(f"Llama charts: {len(data1.get('charts', []))} | Mixtral charts: {len(data2.get('charts', []))}")
    st.caption("Both LLMs received **identical** data, metadata, and instructions.")

st.caption("Built as a clean POC – same context, same JSON schema, different LLMs only.")