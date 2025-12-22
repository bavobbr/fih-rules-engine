
import sys
import os
import json
import time
from typing import List, Dict

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from evals.adapters import BotAdapter, RAGBotAdapter, MockBotAdapter
from langchain_google_vertexai import VertexAI, VertexAIEmbeddings
from logger import get_logger
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall

logger = get_logger(__name__)

class BotEvaluator:
    def __init__(self, bot_adapter: BotAdapter):
        self.bot = bot_adapter
        self.judge_llm = VertexAI(
            model_name=config.LLM_MODEL,
            project=config.PROJECT_ID,
            location=config.REGION,
            temperature=0, # Zero temp for consistent grading
            max_retries=3
        )
        self.embeddings = VertexAIEmbeddings(
            model_name=config.EMBEDDING_MODEL,
            project=config.PROJECT_ID,
            location=config.REGION
        )

    def evaluate_dataset(self, dataset_path: str = "evals/generated_dataset.json"):
        """Run the evaluation loop."""
        if not os.path.exists(dataset_path):
            logger.error(f"Dataset not found: {dataset_path}")
            return

        with open(dataset_path, "r") as f:
            dataset = json.load(f)
            
        logger.info(f"Starting evaluation of {len(dataset)} items...")
        
        results = []
        score_sum = 0
        
        # RAGAS Data Collection
        ragas_data = {
            'question': [],
            'answer': [],
            'contexts': [],
            'ground_truth': []
        }
        
        for i, item in enumerate(dataset):
            question = item["question"]
            ground_truth = item["ground_truth"]
            variant = item.get("variant", "indoor")
            
            logger.info(f"Evaluating Q{i+1}: {question[:50]}...")
            
            # 1. Get Bot Answer via Adapter
            try:
                response = self.bot.query(question)
                bot_answer = response.get("answer", "")
                source_docs = response.get("source_docs", [])
            except Exception as e:
                logger.error(f"Bot failed to answer: {e}")
                bot_answer = "ERROR"
                source_docs = []
                response = {}
            
            # Collect for RAGAS
            ragas_data['question'].append(question)
            ragas_data['answer'].append(bot_answer)
            ragas_data['contexts'].append([doc.page_content for doc in source_docs])
            ragas_data['ground_truth'].append(ground_truth)

            # 2. Check Retrieval Hit Rate
            source_text = item.get("source_text")
            is_hit = False
            if source_text:
                for doc in source_docs:
                    if doc.page_content == source_text:
                        is_hit = True
                        break
            
            # 3. Check Rule Citation (New Metric)
            context_guidance = item.get("context_guidance", "")
            citation_hit = self._check_citation(bot_answer, context_guidance)

            # 4. Grade Answer (Custom Model)
            score, reasoning = self._grade_answer(question, ground_truth, bot_answer)
            score_sum += score
            
            logger.info(f"  -> Score: {score}/1. Hit: {is_hit}. Cited: {citation_hit}.")
            
            results.append({
                "question": question,
                "ground_truth": ground_truth,
                "bot_answer": bot_answer,
                "score": score,
                "retrieval_hit": is_hit if source_text else None,
                "citation_hit": citation_hit,
                "context_guidance": context_guidance,
                "reasoning": reasoning
            })
            
            # Rate limit politeness
            time.sleep(1)
            
        # --- Custom Metrics ---
        accuracy = (score_sum / len(dataset)) * 100
        
        # Calculate Hit Rate (only for items that had source_text)
        items_with_source = [r for r in results if r["retrieval_hit"] is not None]
        hit_rate = 0.0
        if items_with_source:
            hits = sum(1 for r in items_with_source if r["retrieval_hit"])
            hit_rate = (hits / len(items_with_source)) * 100
            
        # Calculate Citation Rate (only for items that had context_guidance)
        items_with_guidance = [r for r in results if r["context_guidance"]]
        citation_rate = 0.0
        if items_with_guidance:
            cites = sum(1 for r in items_with_guidance if r["citation_hit"])
            citation_rate = (cites / len(items_with_guidance)) * 100
            
        logger.info(f"Custom Stats -> Accuracy: {accuracy:.2f}%. Hit Rate: {hit_rate:.2f}%. Citation Rate: {citation_rate:.2f}%")
        
        # --- RAGAS Metrics ---
        logger.info("Running RAGAS evaluation (this takes a moment)...")
        ragas_dataset = Dataset.from_dict(ragas_data)
        
        # Need to wrap VertexAI for Ragas compatibility if needed, 
        # but usually passing the langchain object works for newer ragas versions.
        # Ragas uses 'llm' and 'embeddings' args.
        try:
            ragas_scores = evaluate(
                ragas_dataset,
                metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
                llm=self.judge_llm,
                embeddings=self.embeddings
            )
            ragas_result_mean = ragas_scores.to_pandas().mean(numeric_only=True).to_dict()
            ragas_result_df = ragas_scores.to_pandas()
            
            logger.info(f"RAGAS Scores: {ragas_result_mean}")
            
            # Merge RAGAS scores back into results
            for idx, row in ragas_result_df.iterrows():
                if idx < len(results):
                    results[idx]["ragas"] = {
                        "faithfulness": row.get("faithfulness"),
                        "answer_relevancy": row.get("answer_relevancy"),
                        "context_precision": row.get("context_precision"),
                        "context_recall": row.get("context_recall")
                    }

        except Exception as e:
            logger.error(f"RAGAS evaluation failed: {e}")
            ragas_result_mean = {"error": str(e)}

        # Save detailed report
        report_path = "evals/report_latest.json"
        with open(report_path, "w") as f:
            json.dump({
                "custom_metrics": {
                    "accuracy": accuracy,
                    "hit_rate": hit_rate,
                    "citation_rate": citation_rate
                },
                "ragas_metrics": ragas_result_mean,
                "details": results
            }, f, indent=2)
            
        return accuracy

    def _check_citation(self, bot_answer, context_guidance):
        """
        Checks if the bot cited the rule mentioned in context_guidance.
        context_guidance format: "Derived from 9.12" or "Derived from Rule 9.12"
        """
        if not context_guidance:
            return None
            
        # Extract the rule number(s)
        # We look for digits/dots at the end
        import re
        match = re.search(r"([\d\.]+)", context_guidance.replace("Derived from", ""))
        if not match:
            return None
            
        rule_number = match.group(0).strip()
        
        # Permissive check: Is this rule number in the answer?
        # We check for "Rule 9.12", "[9.12]", "(9.12)" or just "9.12" if surrounded by spaces/punctuation
        return rule_number in bot_answer

    def _grade_answer(self, question, ground_truth, bot_answer):
        """Asks LLM to judge the answer."""
        prompt = f"""
        You are a strict teacher grading an exam.
        
        Question: {question}
        
        Ground Truth Answer: {ground_truth}
        
        Student Answer: {bot_answer}
        
        INSTRUCTIONS:
        1. Compare the Student Answer to the Ground Truth.
        2. If the Student Answer contains the correct key facts, grade it 1.
        3. If it is missing key facts or is wrong, grade it 0.
        4. Ignore minor phrasing differences.
        
        FORMAT:
        Output JSON only: {{"score": 1, "reasoning": "..."}}
        """
        
        try:
            response = self.judge_llm.invoke(prompt).strip()
            response = response.replace("```json", "").replace("```", "")
            grade = json.loads(response)
            return grade.get("score", 0), grade.get("reasoning", "Parse Error")
        except Exception as e:
            logger.error(f"Grading failed: {e}")
            return 0, "Grading Failed"

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Evaluation on a specific Bot implementation.")
    parser.add_argument("--bot", type=str, default="rag", choices=["rag", "mock"], help="Which bot adapter to use.")
    args = parser.parse_args()
    
    if args.bot == "mock":
        adapter = MockBotAdapter()
    else:
        adapter = RAGBotAdapter()
        
    evaluator = BotEvaluator(adapter)
    evaluator.evaluate_dataset()
