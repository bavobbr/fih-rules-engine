
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
STRUCTURE YOUR RESPONSE:
**Reasoning:**
*Explain the logic followed to arrive at the answer step by step. Example: "Since the defender committed an offence in the circle..."*

**Answer:**
- Start with a human-friendly summary.
- If applying a Local Rule, explicitly state: *"In {country_code}, the rule is..."*
- Follow with a **markdown bulleted list** of technical details derived ONLY from the provided CONTEXT.

CITATION RULES:
- For each bullet point, cite the source.
- Use **(Rule <rule>)** or **(Page <page>)**.
- IMPORTANT: If the rule number or page is unknown/missing in the context, DO NOT invent one or write "(Rule unknown)". Just OMIT the specific citation.
- If it is a local rule, append **(local rule)** to the end of the bullet point.

CONTEXT:
{context_text}

QUESTION:
{standalone_query}

ANSWER:
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

def get_reformatting_prompt(original_answer: str, context_text: str) -> str:
    """
    Generates the prompt for reformatting the initial RAG answer.
    """
    return f"""
You are a technical editor for a Field Hockey Rules Assistant.
Your job is to REFORMAT the provided 'Original Answer' into a specific structure without changing the correctness of the answer.

INPUT DATA:
- Original Answer: A detailed Chain-of-Thought response from an expert implementation.
- Context Snippets: The source text used to generate the answer (allow for verifying citations).

FORMAT REQUIREMENTS:
1. **Structure**: 
   - **Direct Answer**: The answer to the user's question. Clear, concise, and upfront.
   - **Key Rules**: A bulleted list of the specific rules applied. 
     - **CRITICAL**: Do NOT just list the rule number. You MUST keep the short explanation or fact from the Original Answer that goes with the citation.
   - **Reasoning**: The detailed explanation (logic/steps) from the original answer.

2. **Styling Rules**:
   - **Rule References**: Must be **bold** (e.g. **Rule 9.11**, **Rule 5**).
   - **Document Names**: Must be *italics* and *lowercase* (e.g. *fih-rules-2024.pdf*, *spelregels-outdoor.pdf*).
   - **Unknowns**: Remove references like "Rule unknown", "p.?", or "Page ?". If you don't know the number, just describe the rule or omit the specific citation number.
   - **Local Rules**: Explicitly label local rule variations if they appear in the answer.

3. **Content Preservation**:
   - Do NOT change the meaning.
   - Do NOT remove important warnings or distinctions (e.g. Outdoor vs Indoor).
   - Use the 'Reasoning' section to keep the deep explanation from the original answer.
   - **CRITICAL**: Start the 'Reasoning' section by explicitly stating what the user is asking (e.g., "The user asks about..."). This interpretation context from the Original Answer must be preserved.

4. **Refusal/Chit-chat Exception**:
   - If the 'Original Answer' states that the question cannot be answered from the rules, is off-topic, or is just a greeting:
     - Return ONLY the polite conversational response.
     - Do NOT include 'Key Rules' or 'Reasoning' sections.
     - Do NOT use any headers (like 'Direct Answer').

Original Answer:
{original_answer}

Context Snippets:
{context_text}

Reformatted Output:
"""
