"""Streamlit UI for the FIH Rules RAG app.

Responsibilities:
- Initialize the engine and report health
- Ingest PDFs with a selected variant
- Provide a lightweight chat interface with routing info
"""

import traceback
import streamlit as st
import warnings

# Suppress warnings from Google Cloud libs regarding future deprecations
# We are blocked from upgrading google-cloud-storage by langchain-google-vertexai
warnings.filterwarnings("ignore", module="google.cloud.aiplatform.models")
warnings.filterwarnings("ignore", category=UserWarning, module="vertexai._model_garden._model_garden_models")
import tempfile
import config
from rag_engine import FIHRulesEngine
from logger import get_logger

logger = get_logger(__name__)

st.set_page_config(page_title="FIH Rules Expert", page_icon="🏑")
st.title("FIH Hockey Rules - RAG Agent")

# Engine initialization (cached across reruns)
@st.cache_resource
def get_app_engine():
    """Create and cache the application engine (LLM + DB)."""
    return FIHRulesEngine()

# Attempt to connect to the engine with visual feedback
try:
    with st.spinner("Connecting to Cloud Knowledge Base..."):
        engine = get_app_engine()
    st.success("✅ Connected to Cloud Knowledge Base")
except Exception as e:
    st.error("Failed to initialize engine. Please check logs.")
    # Log the full traceback internally as JSON
    logger.error("Critical Initialization Error", exc_info=True)
    
    # Optional: logic to show traceback only in dev
    # st.exception(e) 
    st.stop()

# Sidebar: ingest a PDF with a selected ruleset variant
with st.sidebar:
    st.header("📚 Knowledge Base")
    
    uploaded_file = st.file_uploader("Upload Rules PDF", type="pdf")

    # Select which ruleset the uploaded PDF belongs to
    selected_variant = st.selectbox(
        "Select Ruleset Variant",
        options=list(config.VARIANTS.keys()),
        format_func=lambda x: config.VARIANTS[x]
    )
    
    if uploaded_file and st.button("Ingest"):
        with st.spinner(f"Indexing as {config.VARIANTS[selected_variant]}..."):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            
            # Persist with the selected variant label
            count = engine.ingest_pdf(tmp_path, selected_variant, original_filename=uploaded_file.name)
            
            if count == -1:
                st.warning(f"Data for **{selected_variant}** already exists in the Knowledge Base. To overwrite, please clear the database first (admin only).")
            else:
                st.success(f"Successfully indexed {count} rules for {selected_variant}!")

    st.markdown("---")
    st.markdown("👨‍💻 By **Bavo Bruylandt**")
    st.markdown("🔗 [Source Code](https://github.com/bavobbr/langchain-poc)")

# --- CHAT UI ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Persistent state for debug info (only for limits to last query)
if "last_debug" not in st.session_state:
    st.session_state.last_debug = None

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Helper to process a query
def handle_query(query_text):
    st.chat_message("user").markdown(query_text)
    
    with st.chat_message("assistant"):
        with st.spinner("Consulting the rulebook..."):
            history_list = [(m["role"], m["content"]) for m in st.session_state.messages]
            
            # Query the engine with recent message history
            result = engine.query(query_text, history=history_list)
            
            st.markdown(result["answer"])
            
            # Store debug info for persistent display
            st.session_state.last_debug = result
            
    st.session_state.messages.append({"role": "user", "content": query_text})
    st.session_state.messages.append({"role": "assistant", "content": result["answer"]})

# Determine input source: Starter Buttons OR Chat Input
final_prompt = None

# Show Starter Questions if history is empty
# Show Starter Questions if history is empty
starter_container = st.empty()
if not st.session_state.messages:
    with starter_container.container():
        st.markdown("### Get Started with Sample Questions:")
        c1, c2, c3 = st.columns(3)
        if c1.button("Yellow Card Duration"):
            final_prompt = "what is the duration of a yellow card?"
        if c2.button("Deliberate Foul in Circle"):
            final_prompt = "what happens when a defender make a deliberate foul in the circle?"
        if c3.button("Field Dimensions"):
            final_prompt = "how large is the field?"

# Clear starter buttons if a selection was made
if final_prompt and not st.session_state.messages:
    starter_container.empty()

# Chat Input (bottom)
chat_input_prompt = st.chat_input("Ask a question (e.g., 'What about indoor penalty corners?')...")
if chat_input_prompt:
    final_prompt = chat_input_prompt

# Process if we have a valid prompt
if final_prompt:
    handle_query(final_prompt)

# --- PERSISTENT DEBUG SECTION (Outside chat loop) ---
if st.session_state.last_debug:
    debug_data = st.session_state.last_debug
    
    st.divider()
    with st.expander("🛠️ Debug: Routing & Sources (Last Query)", expanded=False):
        st.info(f"🚦 Router selected: **{debug_data['variant'].upper()}**")
        st.write(f"**Reformulated Query:** `{debug_data['standalone_query']}`")
        
        st.subheader("Retrieved Chunks")
        for i, doc in enumerate(debug_data["source_docs"]):
             summary = doc.metadata.get("summary", "No summary available")
             
             # Header with key info
             st.markdown(f"**Source {i+1}**: _{summary}_")
             
             # Full metadata view
             st.json(doc.metadata, expanded=False)

