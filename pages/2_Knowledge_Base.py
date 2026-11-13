import streamlit as st
import pandas as pd
import time
import tempfile
from database import PostgresVectorDB
from rag_engine import FIHRulesEngine
import config
from logger import get_logger

logger = get_logger(__name__)

st.set_page_config(page_title="Knowledge Base", page_icon="📚")
st.title("📚 Knowledge Base Management")

# Initialize Engine (includes DB)
@st.cache_resource
def get_engine():
    return FIHRulesEngine()

engine = get_engine()
db = engine.db

# --- INGESTION SECTION ---
with st.expander("📤 Import New Rules", expanded=False):
    # 1. What is being imported decides the jurisdiction (no separate checkbox to forget)
    import_kind = st.radio(
        "What are you importing?",
        options=["official", "national"],
        format_func=lambda x: "Official FIH rulebook" if x == "official" else "National rules for a country",
        horizontal=True,
        key="ingest_kind"
    )
    is_official = import_kind == "official"

    ingest_country_code = None
    if not is_official:
        countries = {name: code for name, code in config.TOP_50_NATIONS.items() if code}
        selected_country_label = st.selectbox(
            "Country",
            options=list(countries),
            index=None,
            placeholder="Choose a country",
            key="ingest_country"
        )
        ingest_country_code = countries.get(selected_country_label)

    selected_variant = st.selectbox(
        "Variant",
        options=list(config.VARIANTS.keys()),
        format_func=lambda x: config.VARIANTS[x],
        key="ingest_variant"
    )
    variant_label = config.VARIANTS[selected_variant]

    uploaded_file = st.file_uploader(
        "File",
        type=["pdf"] if is_official else ["pdf", "docx", "txt"],
        help="Official rulebooks must be PDF (page layout is analysed). National rules are read as plain text."
    )

    if not is_official and not ingest_country_code:
        st.caption("Choose a country to see what is already imported.")
    else:
        scope_label = "official FIH rulebook" if is_official else f"{selected_country_label} national rules"
        existing_docs = db.get_scope_documents(selected_variant, country_code=ingest_country_code)
        chunk_counts = {d["source_file"]: d["chunk_count"] for d in existing_docs}

        if existing_docs:
            listing = "\n".join(f"- *{name}* ({count} chunks)" for name, count in chunk_counts.items())
            st.markdown(f"**Already imported for {scope_label} · {variant_label}**\n{listing}")
        else:
            st.caption(f"Nothing imported yet for {scope_label} · {variant_label}.")

        if uploaded_file:
            # Same file name is always replaced; another document can optionally be replaced too
            same_name = uploaded_file.name in chunk_counts
            if same_name:
                st.warning(f"*{uploaded_file.name}* is already imported ({chunk_counts[uploaded_file.name]} chunks) and will be replaced.")

            other_docs = [name for name in chunk_counts if name != uploaded_file.name]
            replaces = None
            if other_docs:
                # Two official rulebooks side by side make no sense, so official uploads default to replacing
                replace_index = 1 if is_official and not same_name else 0
                replaces = st.selectbox(
                    "Replaces",
                    options=[None] + other_docs,
                    index=replace_index,
                    format_func=lambda x: "Nothing, keep the other documents" if x is None else x,
                    key="ingest_replaces"
                )

            removed = [name for name in (uploaded_file.name if same_name else None, replaces) if name]
            action = f"Import as {scope_label} · {variant_label}"
            if removed:
                action += f" · replaces {', '.join(removed)}"

            confirmed = True
            if is_official and removed:
                removed_chunks = sum(chunk_counts[name] for name in removed)
                st.error(f"⚠️ This replaces the official FIH {variant_label} rules ({removed_chunks} chunks). Every user's answers depend on these.")
                confirmed = st.checkbox(f"Yes, replace the official {variant_label} rules", key="ingest_confirm")

            if st.button(action, disabled=not confirmed, type="primary"):
                with st.spinner(f"Indexing as {scope_label} · {variant_label}..."):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False) as tmp:
                            tmp.write(uploaded_file.getvalue())
                            tmp_path = tmp.name

                        count = engine.ingest_pdf(
                            tmp_path,
                            selected_variant,
                            country_code=ingest_country_code,
                            original_filename=uploaded_file.name,
                            replaces=replaces
                        )

                        st.success(f"Imported {count} chunks from {uploaded_file.name} as {scope_label} · {variant_label}.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ingestion failed: {e}")
                        logger.error("Ingestion failed", exc_info=True)

st.divider()

st.subheader("Ingested Documents")
st.info("Manage the ingested Rulebooks and National Appendices here.")

# Refresh button
if st.button("🔄 Refresh Data"):
    st.rerun()

# --- Load Data ---
try:
    stats = db.get_source_stats()
    
    if not stats:
        st.warning("No documents found in the database.")
    else:
        # Convert to DataFrame for easier display
        df = pd.DataFrame(stats)
        
        # Display Summary
        total_chunks = df['chunk_count'].sum()
        total_files = len(df)
        col1, col2 = st.columns(2)
        col1.metric("Total Documents", total_files)
        col2.metric("Total Text Chunks", total_chunks)
        
        st.divider()
        st.subheader("Ingested Documents")
        
        # Display as a table with delete buttons
        # Streamlit doesn't support a direct "Action" column in dataframe easily,
        # so we iterate.
        
        # Create a clean display grid
        # Headers
        c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1.5, 1, 1])
        c1.markdown("**File Name**")
        c2.markdown("**Jurisdiction**")
        c3.markdown("**Variant**")
        c4.markdown("**Chunks**")
        c5.markdown("**Action**")
        
        st.divider()
        
        for index, row in df.iterrows():
            c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1.5, 1, 1])
            
            c1.text(row['source_file'])
            c2.text(row['country'])
            c3.text(row['variant'])
            c4.text(str(row['chunk_count']))
            
            # Unique key for button
            btn_key = f"del_{index}"
            if c5.button("🗑️", key=btn_key, help=f"Delete {row['source_file']}"):
                try:
                    with st.spinner(f"Deleting {row['source_file']}..."):
                        db.delete_source_file(
                            row['source_file'],
                            row['variant'],
                            country_code=None if row['country'] == 'Official' else row['country']
                        )
                    st.success(f"Deleted {row['source_file']}")
                    time.sleep(1) # Give user time to see success
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to delete: {e}")
                    logger.error(f"Delete failed: {e}")

except Exception as e:
    st.error(f"Failed to load knowledge base statistics: {e}")
    logger.error("KB Page Error", exc_info=True)
