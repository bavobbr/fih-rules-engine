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

# Metadata values the loaders use when a chunk has no real rule/chapter/section
METADATA_PLACEHOLDERS = ("", "n/a", "general", "front matter", "unknown", "no number")

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
            location=config.LLM_LOCATION,
            temperature=0
        )
        # Database
        self.db = PostgresVectorDB()
        
        # Loaders
        self.loader_official = VertexAILoader()
        self.loader_local = SequentialLoader(chunk_size=1000, chunk_overlap=200)

    # Ingestion
    def ingest_pdf(self, file_path, variant, country_code=None, original_filename=None, replaces=None):
        """Parse a document, chunk, embed and persist under a ruleset variant.

        Existing chunks of a document with the same file name in this scope (variant + country) are
        replaced; other documents in the scope are kept.

        Args:
            country_code: 3-letter ISO/FIH code (e.g. 'BEL'). If None, treats as Official Rules (PDF only).
            replaces: Optional file name of another document in this scope to remove (e.g. last year's version).
        """
        import os

        # 0. Validate Input
        if variant not in config.VARIANTS:
            raise ValueError(f"Invalid variant '{variant}'. Allowed: {list(config.VARIANTS.keys())}")

        source_file = original_filename or os.path.basename(file_path)
        if not country_code and not source_file.lower().endswith(".pdf"):
            raise ValueError("Official FIH rulebooks must be a PDF (structure analysis needs page layout).")

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
        
        # Deduplication: replace this document (and the one it supersedes) within the scope only
        for filename in dict.fromkeys(f for f in (source_file, replaces) if f):
            logger.info(f"Removing existing '{filename}' for variant='{variant}', country='{country_code}'...")
            self.db.delete_source_file(filename, variant, country_code=country_code)
        
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
        
        # Reformulate, route & extract keywords (single LLM call)
        plan = self._plan_query(history, user_input, country_code=country_code)
        standalone_query = plan["standalone_query"]
        detected_variant = plan["variant"]
        # Keywords are OR-ed: websearch_to_tsquery ANDs plain words, which rarely matches a whole question
        keyword_text = " or ".join(plan["keywords"]) or standalone_query
        logger.info(f"Query plan: variant={detected_variant}, standalone='{standalone_query}', keywords='{keyword_text}'")

        # Embed query
        query_vector = self.embeddings.embed_query(standalone_query)

        # --- DUAL-PATH RETRIEVAL ---
        # Path 1: Global Rules (Official) - Always fetch
        results_global = self.db.search_hybrid(
            standalone_query, query_vector, detected_variant, country_code=None,
            k=config.RETRIEVAL_K, keyword_text=keyword_text
        )

        results_local = []
        if country_code:
            # Path 2: Local Rules - Fetch if jurisdiction applies
            results_local = self.db.search_hybrid(
                standalone_query, query_vector, detected_variant, country_code=country_code,
                k=config.RETRIEVAL_K, keyword_text=keyword_text
            )
            
        # Merge Results
        # Simple concatenation (Reranker will sort out relevance)
        combined_results = results_global + results_local
        
        # Convert to Documents
        docs = [Document(page_content=r["content"], metadata=r["metadata"]) for r in combined_results]
        
        # Rerank
        if docs:
            docs = self._rerank_documents(standalone_query, docs)
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
        logger.debug(f"Full Prompt: {full_prompt}")
        answer = self.llm.invoke(full_prompt)
        logger.info(f"Received AI response ({len(answer)} chars)")

        # Render structured answer; fall back to the raw text if the model did not return JSON
        answer_data = self._extract_json(answer)
        if answer_data.get("direct_answer"):
            final_answer = self._render_answer(answer_data)
        else:
            logger.warning("Answer was not valid JSON, returning raw response.")
            final_answer = answer
        
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
                    title=self._rerank_title(doc.metadata),
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

    def _plan_query(self, history, query, country_code=None):
        """Return {variant, standalone_query, keywords} for the latest user message."""
        # Resolve Jurisdiction Label
        jurisdiction_label = "International"
        if country_code:
            # Try to resolve code to name
            code_to_name = {v: k for k, v in config.TOP_50_NATIONS.items() if v is not None}
            jurisdiction_label = code_to_name.get(country_code, f"{country_code} National")

        history_str = "\n".join([f"{role}: {txt}" for role, txt in history[-4:]])
        prompt = prompts.get_query_planning_prompt(history_str, query, jurisdiction_label=jurisdiction_label)
        return self._parse_query_plan(self.llm.invoke(prompt), query)

    @staticmethod
    def _parse_query_plan(raw, original_query):
        """Parse the planner's JSON output, falling back to safe defaults if it is malformed."""
        def to_variant(text):
            # Prefer the most specific match ('hockey5s' text may also mention 'outdoor')
            text = str(text).lower()
            for variant in ("hockey5s", "indoor", "outdoor"):
                if variant in text:
                    return variant
            return "outdoor"

        data = FIHRulesEngine._extract_json(raw)
        if not data:
            logger.warning(f"Could not parse query plan, using original query. Raw output: {raw!r}")
            return {"variant": to_variant(raw), "standalone_query": original_query, "keywords": []}

        keywords = data.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = [keywords]
        return {
            "variant": to_variant(data.get("variant", "outdoor")),
            "standalone_query": str(data.get("standalone_query") or original_query).strip(),
            "keywords": [str(k).strip() for k in keywords if str(k).strip()],
        }

    @staticmethod
    def _rerank_title(metadata):
        """Build a reranker title from rule, chapter and section, skipping placeholders."""
        parts = []
        for key in ("rule", "chapter", "section"):
            value = str(metadata.get(key) or "").strip()
            if value.lower() in METADATA_PLACEHOLDERS:
                continue
            if key == "rule" and value[0].isdigit():
                value = f"Rule {value}"
            parts.append(value)
        return " | ".join(parts)

    @staticmethod
    def _extract_json(raw):
        """Return the first JSON object in an LLM response (tolerates fences and prose), or {}."""
        import json
        import re

        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        try:
            data = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _render_answer(data):
        """Render the structured answer as markdown: Direct Answer > Key Rules > Reasoning."""
        direct_answer = str(data.get("direct_answer", "")).strip()
        if data.get("is_refusal"):
            return direct_answer

        sections = [f"**Direct Answer**\n{direct_answer}"]

        bullets = []
        for item in data.get("key_rules") or []:
            if not isinstance(item, dict):
                continue
            rule = str(item.get("rule", "")).strip()
            # Loader placeholders are not real rule numbers
            if rule.lower() in METADATA_PLACEHOLDERS:
                rule = ""
            elif rule[0].isdigit():
                rule = f"Rule {rule}"

            citation = str(item.get("source_file", "")).strip().lower()
            page = str(item.get("page", "")).strip()
            if page and page != "?":
                citation = f"{citation}, p. {page}" if citation else f"p. {page}"

            bullet = str(item.get("explanation", "")).strip()
            if rule:
                bullet = f"**{rule}**: {bullet}"
            if citation:
                bullet += f" *({citation})*"
            if item.get("is_local"):
                bullet += " (local rule)"
            bullets.append(f"- {bullet}")

        if bullets:
            sections.append("**Key Rules**\n" + "\n".join(bullets))

        reasoning = str(data.get("reasoning", "")).strip()
        if reasoning:
            sections.append(f"**Reasoning**\n{reasoning}")

        return "\n\n".join(sections)
