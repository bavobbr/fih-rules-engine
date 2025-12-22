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
        results = self.db.search(query_vector, detected_variant, k=config.RETRIEVAL_K)
        
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
            heading = meta.get("heading", "Reference")
            chapter = meta.get("chapter", "")
            section = meta.get("section", "")
            
            # Construct Citation Header
            # e.g. [Rule 9.12] [Source: rules.pdf p.42] (Context: PLAYING THE GAME > Field of Play)
            source_file = meta.get("source_file", "unknown")
            page_num = meta.get("page", "?")
            
            context_string = f"[{heading}] [Source: {source_file} p.{page_num}]"
            if chapter or section:
                context_string += f" (Context: {chapter} > {section})"
            
            context_pieces.append(f"{context_string}\n{d.page_content}")

        context_text = "\n\n".join(context_pieces)
        
        if not context_text:
            return {
                "answer": f"I checked the **{detected_variant}** rules but couldn't find an answer.",
                "standalone_query": standalone_query,
                "variant": detected_variant,
                "source_docs": []
            }

        full_prompt = f"""
        Expert FIH international Field Hockey Umpire for {detected_variant.upper()}. 
        Answer based on Context. Cite Rules.
        
        CONTEXT:
        {context_text}
        
        QUESTION:
        {standalone_query}
        """
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
                    title=doc.metadata.get("heading", ""),
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
        prompt = f"""Given the following conversation and a follow up question about Field Hockey, rephrase the follow up question to be a standalone question.
        Do NOT answer the question. Just rewrite it to be self-contained and have all the relevant context provided.
        First analyze the hockey variant (outdoor, indoor, hockey5s) from the given context. If not clear from context, default to outdoor. 
        Prepend the variant in a strict format: [VARIANT: <variant>]
        
        Example question:
        In indoor hockey can a player hit the ball?

        Example output:
        [VARIANT: indoor] Can a player hit the ball?
        
        Chat History:
        {history_str}
        
        Follow Up Input: {query}
        
        Standalone Question:"""
        return self.llm.invoke(prompt).strip()

    def _route_query(self, query):
        """Return 'outdoor' | 'indoor' | 'hockey5s' based on content."""
        prompt = f"Analyze Field Hockey question and categorize it as outdoor, indoor or hockey5s variant. Return 'outdoor', 'indoor', or 'hockey5s'. Default to 'outdoor'.\nQUESTION: {query}"
        return self.llm.invoke(prompt).strip().lower().replace("'", "").replace('"', "")
