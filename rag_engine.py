"""Core RAG engine for FIH Rules.

Provides ingestion (chunking + embeddings + persistence) and query handling
(contextualization, routing, retrieval, and synthesis).
"""


from langchain_core.documents import Document
import config
from database import PostgresVectorDB
from logger import get_logger

logger = get_logger(__name__)

class FIHRulesEngine:
    """High-level interface to embeddings, LLM, and vector DB."""

    def __init__(self):
        from langchain_google_vertexai import VertexAIEmbeddings, VertexAI
        from google.cloud import discoveryengine_v1 as discoveryengine
        
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

    # Ingestion
    def ingest_pdf(self, file_path, variant, original_filename=None):
        """Parse a PDF, chunk, embed and persist under a ruleset variant.

        Validates 'variant' against config.VARIANTS to prevent unauthorized data creation.
        """
        # 0. Validate Input
        if variant not in config.VARIANTS:
            raise ValueError(f"Invalid variant '{variant}'. Allowed: {list(config.VARIANTS.keys())}")

        # 1. Ensure Schema
        self.db.ensure_schema()

        # 2. Ingest
        # Dynamically load the configured loader (Online vs Batch) 
        # Lazy import loaders
        import loaders
        docai_loader = loaders.get_document_ai_loader()
        docs = docai_loader.load_and_chunk(file_path, variant, original_filename=original_filename)

        if not docs:
            logger.warning("No chunks generated!")
            return 0
        
        # Deduplication: Clear existing data for this variant
        logger.info(f"Cleaning existing '{variant}' data...")
        self.db.delete_variant(variant)
        
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
    def query(self, user_input, history=[]):
        """Answer a user question using contextualization, routing, and RAG."""
        logger.info(f"Query: {user_input}")
        
        # Reformulate & route
        standalone_query = self._contextualize_query(history, user_input)
        logger.info(f"Standalone Query: {standalone_query}")
        
        detected_variant = self._route_query(standalone_query)
        if detected_variant not in config.VARIANTS: 
            detected_variant = "outdoor"
        # Clean query for embedding (propagate intent, not routing instruction)
        import re
        # Remove [VARIANT: ...] prefix to avoid semantic drift
        # Matches "[VARIANT: indoor] Can I..." or "[VARIANT: indoor hockey] Can I..."
        clean_query = re.sub(r"^\[VARIANT:.*?\]\s*", "", standalone_query, flags=re.IGNORECASE)
        
        # Embed query
        query_vector = self.embeddings.embed_query(clean_query)
        # Retrieve
        results = self.db.search_hybrid(clean_query, query_vector, detected_variant, k=config.RETRIEVAL_K)
        
        # Convert DB results back to LangChain Documents for consistency
        docs = [Document(page_content=r["content"], metadata=r["metadata"]) for r in results]
        
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
            # e.g. [Rule 9.12] [Source: rules.pdf p.42] (Context: PLAYING THE GAME > Field of Play)
            source_file = meta.get("source_file", "unknown")
            page_num = meta.get("page", "?")
            
            context_string = f"[Source: {source_file} p.{page_num}]"
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

        full_prompt = f"""
You are an expert FIH international Field Hockey Umpire for {detected_variant}.
You are provided with a set of rules for {detected_variant} hockey and their metadata fields source, page, rule, chapter, section where available.

STRUCTURE YOUR RESPONSE:
- Start with a human-friendly, summary of the answer as a plain paragraph.
- Follow with a **markdown bulleted list** of technical details derived ONLY from the provided CONTEXT, when they are relevant to the question.
- Do NOT use labels like "Summary", "Details", "1.", or "2." to demarcate these sections.

CITATION RULES:
- For each bullet point in the technical details, try to cite the rule or page source. Prefer rules over pages where available. You can use both.
    - **If the rule for that point is a number** (e.g., "9.1", "12"), use: **(rule <rule>)**
    - **If the rule for that point is missing, use: **(page <page>)**
    - Use double asterisks for citations as shown above.

CONTEXT:
{context_text}

QUESTION:
{standalone_query}

ANSWER:
"""
        # logger.info(f"Full Prompt: {full_prompt}")
        answer = self.llm.invoke(full_prompt)
        logger.info(f"Received AI response ({len(answer)} chars)")
        
        return {
            "answer": answer,
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

    def _contextualize_query(self, history, query):
        """Rewrite the latest user message as a standalone query."""
        if not history: return query
        history_str = "\n".join([f"{role}: {txt}" for role, txt in history[-4:]])
        prompt = f"""Given the following conversation and a follow up user input about Field Hockey.

YOUR GOAL:
Rephrase the 'Follow Up Input' to be a standalone question, using the 'Chat History' ONLY to resolve pronouns (it, they, that) or ambiguous references to the previous topic.

RULES:
1. If the 'Follow Up Input' is a valid follow-up question, rewrite it to be fully self-contained including the hockey variant.
2. If the 'Follow Up Input' is completely unrelated to the previous context or is gibberish/nonsense, DO NOT change it. Return it exactly as is (but still add the variant tag).
3. Do NOT attempt to answer the question.
4. First analyze the hockey variant (outdoor, indoor, hockey5s) from the context. Default to 'outdoor' if unclear.
5. Prepend the variant in a strict format: [VARIANT: <variant>]

Chat History:
{history_str}

Follow Up Input: {query}

Standalone Question:"""
        return self.llm.invoke(prompt).strip()

    def _route_query(self, query):
        """Return 'outdoor' | 'indoor' | 'hockey5s' based on content."""
        prompt = f"Analyze Field Hockey question and categorize it as outdoor, indoor or hockey5s variant. Return 'outdoor', 'indoor', or 'hockey5s'. Default to 'outdoor'.\nQUESTION: {query}"
        return self.llm.invoke(prompt).strip().lower().replace("'", "").replace('"', "")
