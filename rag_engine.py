"""Core RAG engine for FIH Rules.

Provides ingestion (chunking + embeddings + persistence) and query handling
(contextualization, routing, retrieval, and synthesis).
"""


from langchain_core.documents import Document
import config
from database import PostgresVectorDB
from logger import get_logger

from loaders.vertex_ai_loader import VertexAILoader
from loaders.sequential_loader import SequentialLoader
import prompts

logger = get_logger(__name__)

class FIHRulesEngine:
    """High-level interface to embeddings, LLM, and vector DB."""

    def __init__(self):
        from langchain_google_vertexai import VertexAIEmbeddings, VertexAI
        
        # Models
        self.embeddings = VertexAIEmbeddings(
            model_name=config.EMBEDDING_MODEL, 
            project=config.PROJECT_ID, 
            location=config.REGION
        )
        self.llm = VertexAI(
            model_name=config.LLM_MODEL,
            project=config.PROJECT_ID,
            location=config.REGION,
            temperature=0
        )
        # Database
        self.db = PostgresVectorDB()
        
        # Loaders
        self.loader_official = VertexAILoader()
        self.loader_local = SequentialLoader(chunk_size=1000, chunk_overlap=200)

    # Ingestion
    def ingest_pdf(self, file_path, variant, country_code=None, original_filename=None, clear_existing=True):
        """Parse a PDF, chunk, embed and persist under a ruleset variant.
        
        Args:
            country_code: 3-letter ISO/FIH code (e.g. 'BEL'). If None, treats as Official Rules.
            clear_existing: If True, deletes existing rules for this scope before ingesting (Replace Mode).
                            If False, keeps existing rules and adds new ones (Append Mode).
        """
        # 0. Validate Input
        if variant not in config.VARIANTS:
            raise ValueError(f"Invalid variant '{variant}'. Allowed: {list(config.VARIANTS.keys())}")

        # 1. Ensure Schema
        self.db.ensure_schema()

        # 2. Ingest
        # Dynamically load the configured loader (Online vs Batch) 
        if country_code:
            # Local Rulebook -> Sequential Loading (Unstructured)
            logger.info(f"Ingesting Local Rules for {country_code} (Sequential Mode)...")
            # Use the pre-configured loader with correct chunk settings
            docs = self.loader_local.load_and_chunk(file_path, variant, original_filename=original_filename)
            
            # Enrich with Country Metadata
            for d in docs:
                d.metadata["country"] = country_code
                d.metadata["type"] = "local"
        else:
            # Official Rulebook -> Document AI (Structured + Vertex Analysis)
            logger.info(f"Ingesting Official Rules for {variant} (Vertex AI Mode)...")
            # Use official loader logic (could use self.loader_official, but typical pattern uses factory)
            # Keeping existing factory pattern for official to minimize risk
            import loaders
            docai_loader = loaders.get_document_ai_loader()
            docs = docai_loader.load_and_chunk(file_path, variant, original_filename=original_filename)
            
            # Enrich with Official Tag
            for d in docs:
                d.metadata["type"] = "official"

        if not docs:
            logger.warning("No chunks generated!")
            return 0
        
        # Deduplication: scoped deletion (Only if clear_existing is True)
        if clear_existing:
            logger.info(f"Cleaning existing data for variant='{variant}', country='{country_code}'...")
            self.db.delete_scoped_data(variant, country_code=country_code)
        else:
            logger.info(f"Append Mode: Preserving existing data for variant='{variant}', country='{country_code}'.")
        
        # Embed
        logger.info(f"Generating embeddings for {len(docs)} chunks...")
        texts = [d.page_content for d in docs]
        metadatas = [d.metadata for d in docs]
        vectors = self.embeddings.embed_documents(texts)
        
        # Persist
        self.db.insert_batch(texts, vectors, variant, metadatas=metadatas)
        logger.info(f"Persisted {len(docs)} chunks to DB.")
        
        return len(docs)

    # Querying
    def list_jurisdictions(self):
        """
        List all jurisdictions (countries) that have local rules ingested.
        Returns a list of dicts: [{"code": "BEL", "name": "Belgium"}, ...]
        """
        active_codes = self.db.get_active_jurisdictions()
        
        # Reverse map TOP_50_NATIONS to get code -> name
        # The config has Name -> Code (e.g. "Belgium": "BEL")
        # We need to find the name for each active code.
        code_to_name = {v: k for k, v in config.TOP_50_NATIONS.items() if v is not None}
        
        results = []
        for code in active_codes:
            # Default to the code itself if name not found in TOP 50 (e.g. custom ingest)
            name = code_to_name.get(code, f"Unknown ({code})")
            results.append({"code": code, "name": name})
            
        # Sort by name for UI convenience
        results.sort(key=lambda x: x["name"])
        return results

    def query(self, user_input, history=[], country_code=None):
        """Answer a user question using contextualization, routing, and RAG.
        
        Strategies:
        - Route to correct variant (Indoor/Outdoor).
        - Dual-Path Retrieval: Fetch Global Rules AND Local Rules separately.
        - Merge & Rerank.
        """
        logger.info(f"Query: {user_input} [Country: {country_code}]")
        
        # Reformulate & route
        standalone_query = self._contextualize_query(history, user_input, country_code=country_code)
        logger.info(f"Standalone Query: {standalone_query}")
        
        detected_variant = self._route_query(standalone_query)
        if detected_variant not in config.VARIANTS: 
            detected_variant = "outdoor"
        
        import re
        # Remove [VARIANT: ...] prefix
        clean_query = re.sub(r"^\[VARIANT:.*?\]\s*", "", standalone_query, flags=re.IGNORECASE)
        
        # Embed query
        query_vector = self.embeddings.embed_query(clean_query)
        
        # --- DUAL-PATH RETRIEVAL ---
        # Path 1: Global Rules (Official) - Always fetch
        results_global = self.db.search_hybrid(
            clean_query, query_vector, detected_variant, country_code=None, k=config.RETRIEVAL_K
        )
        
        results_local = []
        if country_code:
            # Path 2: Local Rules - Fetch if jurisdiction applies
            results_local = self.db.search_hybrid(
                clean_query, query_vector, detected_variant, country_code=country_code, k=config.RETRIEVAL_K
            )
            
        # Merge Results
        # Simple concatenation (Reranker will sort out relevance)
        combined_results = results_global + results_local
        
        # Convert to Documents
        docs = [Document(page_content=r["content"], metadata=r["metadata"]) for r in combined_results]
        
        # Rerank
        if docs:
            docs = self._rerank_documents(clean_query, docs)
            # Limit to RANKING_TOP_N
            docs = docs[:config.RANKING_TOP_N]
        
        # Synthesize answer
        context_pieces = []
        for d in docs:
            meta = d.metadata
            # Fallback values if metadata is empty/legacy
            rule = meta.get("rule", "")
            chapter = meta.get("chapter", "")
            section = meta.get("section", "")
            
            # Construct Citation Header
            source_file = meta.get("source_file", "unknown")
            country = meta.get("country")
            
            # Explicit Source Tag for LLM
            if country:
                origin_tag = f"[SOURCE: LOCAL ({country})]"
            else:
                origin_tag = "[SOURCE: OFFICIAL]"

            page_num = meta.get("page", "?")
            
            context_string = f"{origin_tag} [File: {source_file} p.{page_num}]"
            if rule:
                context_string += f" [Rule: {rule}]"
            if chapter or section:
                context_string += f" [Chapter: {chapter} > {section}]"
            
            context_pieces.append(f"---Snippet Start---\n{context_string}\n{d.page_content}\n---Snippet End---")

        context_text = "\n\n".join(context_pieces)
        
        if not context_text:
            return {
                "answer": f"I checked the **{detected_variant}** rules but couldn't find an answer.",
                "standalone_query": standalone_query,
                "variant": detected_variant,
                "source_docs": []
            }

        jurisdiction_label = f"{country_code} National" if country_code else "International"

        full_prompt = prompts.get_rag_answer_prompt(
            detected_variant=detected_variant,
            jurisdiction_label=jurisdiction_label,
            country_code=country_code,
            context_text=context_text,
            standalone_query=standalone_query
        )
        logger.info(f"Full Prompt: {full_prompt}")
        answer = self.llm.invoke(full_prompt)
        logger.info(f"Received AI response ({len(answer)} chars)")
        
        # --- SECOND PASS: REFORMATTING ---
        logger.info("Starting Second Pass (Reformatting)...")
        final_answer = self._reformat_response(answer, context_text)
        logger.info(f"Reformatting complete ({len(final_answer)} chars)")
        
        return {
            "answer": final_answer,
            "original_answer": answer,
            "standalone_query": standalone_query,
            "variant": detected_variant,
            "source_docs": docs
        }

    def _rerank_documents(self, query, docs):
        """Rerank documents using Vertex AI Ranking API."""
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine
            
            client = discoveryengine.RankServiceClient()
            
            ranking_config = f"projects/{config.PROJECT_ID}/locations/global/rankingConfigs/default_ranking_config"
            
            records = []
            for i, doc in enumerate(docs):
                records.append(discoveryengine.RankingRecord(
                    id=str(i),
                    title=doc.metadata.get("rule", ""),
                    content=doc.page_content
                ))
            
            request = discoveryengine.RankRequest(
                ranking_config=ranking_config,
                model=config.RANKING_MODEL,
                top_n=config.RANKING_TOP_N,
                query=query,
                records=records,
            )
            
            response = client.rank(request=request)
            
            # Reorder docs based on ranking results
            new_docs = []
            for record in response.records:
                idx = int(record.id)
                new_docs.append(docs[idx])
            
            logger.info(f"Reranked {len(docs)} documents down to {len(new_docs)}")
            return new_docs
            
        except Exception as e:
            logger.error(f"Error during reranking: {e}. Falling back to original retrieval.")
            return docs

    def _contextualize_query(self, history, query, country_code=None):
        """Rewrite the latest user message as a standalone query."""
        if not history: return query
        
        # Resolve Jurisdiction Label
        jurisdiction_label = "International"
        if country_code:
            # Try to resolve code to name
            code_to_name = {v: k for k, v in config.TOP_50_NATIONS.items() if v is not None}
            jurisdiction_label = code_to_name.get(country_code, f"{country_code} National")

        history_str = "\n".join([f"{role}: {txt}" for role, txt in history[-4:]])
        prompt = prompts.get_contextualization_prompt(history_str, query, jurisdiction_label=jurisdiction_label)
        return self.llm.invoke(prompt).strip()

    def _route_query(self, query):
        """Return 'outdoor' | 'indoor' | 'hockey5s' based on content."""
        prompt = prompts.get_routing_prompt(query)
        return self.llm.invoke(prompt).strip().lower().replace("'", "").replace('"', "")

    def _reformat_response(self, original_answer, context_text):
        """
        Uses a second LLM pass to reformat the answer into:
        Answer > Citations > Reasoning.
        """
        reformat_prompt = prompts.get_reformatting_prompt(original_answer, context_text)
        return self.llm.invoke(reformat_prompt)
