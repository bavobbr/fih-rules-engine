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
    st.info("Upload PDF rulebooks or national appendices here.")
    
    c1, c2 = st.columns(2)
    
    with c1:
        # Select Jurisduciton for Ingestion
        selected_country_label = st.selectbox(
            "Select Jurisdiction",
            options=list(config.TOP_50_NATIONS.keys()),
            index=0,
            key="ingest_country"
        )
        ingest_country_code = config.TOP_50_NATIONS[selected_country_label]
    
    with c2:
        # Select Ruleset Variant
        selected_variant = st.selectbox(
            "Select Ruleset Variant",
            options=list(config.VARIANTS.keys()),
            format_func=lambda x: config.VARIANTS[x],
            key="ingest_variant"
        )

    uploaded_file = st.file_uploader("Upload Rules PDF", type="pdf")
    
    # Context Options
    is_national_appendix = st.checkbox("Is this a National Appendix?", value=False)
    append_mode = st.checkbox("Append to existing knowledge base? (Don't delete)", value=False, help="If checked, new rules will be added without deleting existing ones for this jurisdiction.")

    if uploaded_file and st.button("Ingest Document"):
        # Validation
        if is_national_appendix and not ingest_country_code:
            st.error("You must select a country (not International) to upload a National Appendix.")
        else:
            label = f"{config.VARIANTS[selected_variant]} ({ingest_country_code or 'Official'})"
            with st.spinner(f"Indexing as {label}..."):
                try:
                    with tempfile.NamedTemporaryFile(delete=False) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name
                    
                    # Persist with selected mode
                    clear_flag = not append_mode
                    
                    # Use the code if national appendix is checked, otherwise Official (None)
                    # Use explicit logic: If National App -> Use Code. If not -> Use None (Official).
                    # But wait, what if I select Belgium but NOT National Appendix? 
                    # The UI implies "Jurisdiction" is the target. 
                    # If I select Belgium and NOT "National Appendix", does that mean I'm uploading Official Rules FOR Belgium? no.
                    # Let's align with Query.py logic:
                    final_country_code = ingest_country_code if is_national_appendix else None
                    
                    count = engine.ingest_pdf(
                        tmp_path, 
                        selected_variant, 
                        country_code=final_country_code,
                        original_filename=uploaded_file.name,
                        clear_existing=clear_flag
                    )
                    
                    mode_msg = "Appended" if append_mode else "Replaced"
                    st.success(f"Successfully indexed {count} rules for {label}! ({mode_msg})")
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
                        db.delete_source_file(row['source_file'])
                    st.success(f"Deleted {row['source_file']}")
                    time.sleep(1) # Give user time to see success
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to delete: {e}")
                    logger.error(f"Delete failed: {e}")

except Exception as e:
    st.error(f"Failed to load knowledge base statistics: {e}")
    logger.error("KB Page Error", exc_info=True)
