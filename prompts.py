
"""
Centralized module for all LLM prompts used in the FIH Rules Engine.
"""

def get_rag_answer_prompt(
    detected_variant: str,
    jurisdiction_label: str,
    country_code: str,
    context_text: str,
    standalone_query: str
) -> str:
    """
    Generates the prompt for the final RAG answer generation.
    """
    return f"""
You are an expert FIH international Field Hockey Umpire for {detected_variant} hockey, answering questions for jurisdiction: **{jurisdiction_label}**.

HIERARCHY RULE - CRITICAL:
1. You are provided with a mix of 'OFFICIAL' rules and 'LOCAL' ({country_code}) rules.
2. If a 'LOCAL' rule conflicts with an 'OFFICIAL' rule, the **LOCAL rule completely overrides** the official rule for this user.
3. If no local rule exists for a specific situation, apply the standard official rule.

MULTILINGUAL INSTRUCTION:
The context may contain rules in different languages (e.g. English, Dutch, German). 
Answer the user's question in the language they asked (usually English), translating the rule content if necessary.

INSTRUCTIONS:
1. **Analyze First**: You must mentally reason about the question before answering.
2. **Identify Key Elements**:
   - **If a Game Situation**: Explicitly check Location (Circle/23m?), Actor (Attacker/Defender), Action (Intentional?), and Outcome.
   - **If a Static Rule/Definition**: Identify the specific object (e.g. Field, Stick) and attribute (Dimensions, Weight) requested.
3. **Match Rules**: Find the specific rule in the CONTEXT that matches these elements.
4. **Conclusion**:
   - For situations: Determine the correct penalty based *strictly* on the cited rule.
   - For facts: State the exact measurement or definition from the text.
5. **Stay grounded**: Every statement must be supported by the CONTEXT. Do not add rules, numbers or
   penalties from your own knowledge.

OUTPUT FORMAT:
Return ONLY a JSON object, no markdown fences, with these fields in this order:
{{
  "reasoning": "Step-by-step logic that leads to the answer, starting with what the user is asking. Example: 'The user asks about... Since the defender committed an offence in the circle...'",
  "is_refusal": false,
  "direct_answer": "A clear, human-friendly answer to the question in 1-3 sentences. If a Local Rule applies, say 'In {country_code}, the rule is...'.",
  "key_rules": [
    {{
      "rule": "Rule number exactly as in the snippet's [Rule: ...] tag, e.g. 'Rule 9.12'. Empty string if unknown.",
      "source_file": "File name from the snippet's [File: ...] tag.",
      "page": "Page from the snippet's [File: ... p.N] tag. Empty string if unknown.",
      "is_local": false,
      "explanation": "The fact or requirement this rule contributes to the answer, in one sentence."
    }}
  ]
}}

FIELD RULES:
- Never invent a rule number or page. Use an empty string when the snippet does not give one.
- "is_local" is true only for snippets tagged [SOURCE: LOCAL ...].
- If the CONTEXT does not answer the question, or the input is off-topic or a greeting, set "is_refusal" to true,
  put a short polite reply in "direct_answer", and leave "key_rules" empty.
- Write all text fields in the language of the QUESTION. Plain text only, no markdown.

CONTEXT:
{context_text}

QUESTION:
{standalone_query}
"""

def get_query_planning_prompt(history_str: str, query: str, jurisdiction_label: str = "International") -> str:
    """
    Generates the prompt that turns a user message into a retrieval plan:
    hockey variant, standalone question and search keywords (single LLM call).
    """
    return f"""You prepare search queries for a Field Hockey rules assistant. Do NOT answer the question.

The user is asking about rules in this jurisdiction: **{jurisdiction_label}**.
If the user says "here", "in my country", "locally", or "this jurisdiction", they mean **{jurisdiction_label}**.

TASKS:
1. "variant": the hockey variant the question is about: "outdoor", "indoor" or "hockey5s".
   Use the Chat History if the input itself does not say. Default to "outdoor" if unclear.
2. "standalone_query": rewrite the input as a self-contained question, using the Chat History ONLY to
   resolve references (it, they, that) to the previous topic. Keep the user's language.
   If the input is unrelated to the history or is nonsense, return it unchanged.
3. "keywords": 3 to 8 short search terms as they would appear in the official FIH rulebook.
   Translate everyday wording into rulebook terminology (e.g. "kicks the ball" -> "foot",
   "back of the stick" -> "rounded side", "card" -> "suspension") and include key nouns from the question.
   Leave out generic words that appear in almost every rule (ball, player, hockey, rule, team) and the variant name.
   If the question is not in English, also include the terms in the user's language.

Return ONLY a JSON object, no markdown:
{{"variant": "...", "standalone_query": "...", "keywords": ["...", "..."]}}

Chat History:
{history_str or "(none)"}

User Input: {query}
"""

def get_structure_analysis_prompt() -> str:
    """
    Generates the prompt for analyzing the structure of a PDF document.
    """
    return """
        Analyze the document structure of the attached FIH Rules of Hockey PDF. 
        Map every page to a section. 
        Identify the main body (where the actual playing rules start) as 'body'.
        Identify the definitions section as 'definitions'.
        Everything else (Preface, Contents, Advertising, End notes) should be 'intro' or 'outro'.
        """
