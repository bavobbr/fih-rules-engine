
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

def get_contextualization_prompt(history_str: str, query: str, jurisdiction_label: str = "International") -> str:
    """
    Generates the prompt for contextualizing a follow-up question.
    """
    return f"""Given the following conversation and a follow up user input about Field Hockey.

YOUR GOAL:
Rephrase the 'Follow Up Input' to be a standalone question, using the 'Chat History' ONLY to resolve pronouns (it, they, that) or ambiguous references to the previous topic.
Keep the language as used, if not sure use english.

CONTEXT INFORMATION:
The user is currently asking about rules in this jurisdiction: **{jurisdiction_label}**.
If the user says "here", "in my country", "locally", or "this jurisdiction", they are referring to **{jurisdiction_label}**.

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

def get_routing_prompt(query: str) -> str:
    """
    Generates the prompt for routing a query to the correct variant (outdoor, indoor, hockey5s).
    """
    return f"Analyze Field Hockey question and categorize it as outdoor, indoor or hockey5s variant. Return 'outdoor', 'indoor', or 'hockey5s'. Default to 'outdoor'.\nQUESTION: {query}"

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
