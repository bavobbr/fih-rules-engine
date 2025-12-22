import streamlit as st
import json
import pandas as pd
import os
import plotly.express as px

st.set_page_config(page_title="Evaluation Dashboard", page_icon="📊", layout="wide")

st.title("📊 RAG Evaluation Dashboard")

REPORT_PATH = "evals/report_latest.json"

def load_data():
    if not os.path.exists(REPORT_PATH):
        return None
    with open(REPORT_PATH, "r") as f:
        return json.load(f)

data = load_data()

if not data:
    st.warning(f"No evaluation report found at `{REPORT_PATH}`. Please run `python evals/evaluate.py` first.")
    st.stop()

# --- Top Level Metrics ---
st.header("📈 Key Performance Indicators (KPIs)")

cols = st.columns(4)

# Custom Metrics
custom = data.get("custom_metrics", {})
accuracy = custom.get("accuracy", 0)
hit_rate = custom.get("hit_rate", 0)
citation_rate = custom.get("citation_rate", 0)

cols[0].metric("Bot Accuracy", f"{accuracy:.1f}%", help="Percentage of answers graded 'Correct'")
cols[1].metric("Retrieval Hit Rate", f"{hit_rate:.1f}%", help="Correct source text found in retrieval")
cols[2].metric("Rule Citation Rate", f"{citation_rate:.1f}%", help="Correct Rule Number cited in answer")

# RAGAS Metrics
ragas = data.get("ragas_metrics", {})
if ragas:
    faithfulness = ragas.get("faithfulness", 0) * 100
    precision = ragas.get("context_precision", 0) * 100
    
    cols[3].metric("RAGAS Faithfulness", f"{faithfulness:.1f}%", help="Factuality check")

    # Radar Chart or Bar Chart
    st.subheader("🔍 RAGAS Deep Dive")
    ragas_df = pd.DataFrame({
        "Metric": ["Faithfulness", "Answer Relevancy", "Context Precision", "Context Recall"],
        "Score": [ragas.get("faithfulness", 0), ragas.get("answer_relevancy", 0), 
                  ragas.get("context_precision", 0), ragas.get("context_recall", 0)]
    })
    st.bar_chart(ragas_df.set_index("Metric"))

# --- Detailed Breakdown ---
st.header("📝 Detailed Metrics Analysis")

details = data.get("details", [])
if details:
    # Flatten the data structure
    flat_data = []
    for d in details:
        row = {
            "question": d.get("question"),
            "ground_truth": d.get("ground_truth"),
            "bot_answer": d.get("bot_answer"),
            "score": d.get("score"),
            "retrieval_hit": d.get("retrieval_hit"),
            "reasoning": d.get("reasoning")
        }
        # Add RAGAS metrics if available
        ragas_d = d.get("ragas", {})
        if ragas_d:
            row["faithfulness"] = ragas_d.get("faithfulness")
            row["answer_relevancy"] = ragas_d.get("answer_relevancy")
            row["context_precision"] = ragas_d.get("context_precision")
            row["context_recall"] = ragas_d.get("context_recall")
            
        flat_data.append(row)
        
    df = pd.DataFrame(flat_data)
    
    # Configure columns for the Metrics Table
    column_config = {
        "question": st.column_config.TextColumn("Question", width="medium", help="The user query"),
        "score": st.column_config.NumberColumn("Acc", format="%d", help="Judge Score (0/1)"),
        "retrieval_hit": st.column_config.CheckboxColumn("Hit?", help="Did we find the source chunk?"),
        "citation_hit": st.column_config.CheckboxColumn("cited?", help="Did the bot cite the rule number?"),
    }
    
    # Add RAGAS columns if they exist
    if "faithfulness" in df.columns:
        column_config.update({
            "faithfulness": st.column_config.ProgressColumn("Faithfulness", min_value=0, max_value=1, format="%.2f"),
            "answer_relevancy": st.column_config.ProgressColumn("Relevancy", min_value=0, max_value=1, format="%.2f"),
            "context_precision": st.column_config.ProgressColumn("Precision", min_value=0, max_value=1, format="%.2f"),
            "context_recall": st.column_config.ProgressColumn("Recall", min_value=0, max_value=1, format="%.2f"),
        })
        
        wanted_cols = ["question", "score", "retrieval_hit", "citation_hit", "faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    else:
        wanted_cols = ["question", "score", "retrieval_hit", "citation_hit", "reasoning"]

    # Filter columns that actually exist in the dataframe to avoid KeyErrors
    display_cols = [c for c in wanted_cols if c in df.columns]

    st.dataframe(
        df[display_cols],
        column_config=column_config,
        use_container_width=True,
        hide_index=True
    )
    
    # Drill Down Section
    st.subheader("🔍 inspect Specific QA Pair")
    selected_q = st.selectbox("Select a Question to inspect", df["question"])
    if selected_q:
        row = df[df["question"] == selected_q].iloc[0]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**User Question:**")
            st.info(row["question"])
            st.markdown("**Ground Truth:**")
            st.success(row["ground_truth"])
        with c2:
            st.markdown("**Bot Answer:**")
            st.warning(row["bot_answer"])
            st.markdown("**Judge Reasoning:**")
            st.caption(row["reasoning"])


else:
    st.info("No detailed records found in the report.")
