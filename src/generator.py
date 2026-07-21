import json
from groq import Groq
from src import config
from src import uniqueness
from src import verification

client = Groq(api_key=config.GROQ_API_KEY)


def build_generation_prompt(spec: dict, grounding: str) -> list[dict]:
    """Assemble the instructions + context we send to the LLM."""
    needs_marks = spec.get("assessment_type") in config.MARKS_REQUIRED_TYPES
    fmt = spec.get("question_format", "written")

    marks_rule = (
        "Assign a 'marks' value (integer) to each question based on its "
        "difficulty. Harder questions are worth more. Multiple-correct MCQs "
        "should be worth more than single-correct ones."
        if needs_marks else
        "Set 'marks' to null for every question."
    )

    if fmt == "mcq":
        format_rule = (
            "Every question must be multiple-choice (MCQ). Mix single-correct "
            "and multiple-correct questions."
        )
    elif fmt == "mixed":
        format_rule = (
            "Use a mix of written-answer and multiple-choice (MCQ) questions."
        )
    else:
        format_rule = "Every question must be written-answer (no options)."

    system = (
        "You are an expert exam setter creating ORIGINAL questions.\n"
        "Rules:\n"
        "1. Every question must be newly written by you. Never copy the "
        "reference material — use it only to match topics, style, and difficulty.\n"
        "2. Match the exact grade, subject, and difficulty given.\n"
        "3. Write ALL mathematics in plain readable text, NOT LaTeX. "
        "Use plain symbols: write 2^3 (not $2^3$), 1/2 (not \\frac{1}{2}), "
        "sqrt(16) or the square root symbol (not \\sqrt{16}). "
        "Never use dollar signs, backslashes, or LaTeX commands.\n"
        f"4. {marks_rule}\n"
        "5. Each question object must have these fields:\n"
        "   - 'number': integer\n"
        "   - 'topic': short topic name\n"
        "   - 'q_type': 'written', 'single' (one correct option), or "
        "'multiple' (more than one correct option)\n"
        "   - 'question': the question text\n"
        "   - 'options': for MCQs, a list like ['A) ...','B) ...','C) ...',"
        "'D) ...']; for written, an empty list []\n"
        "   - 'correct_options': for MCQs, a list of correct letters like "
        "['B'] or ['A','C']; for written, an empty list []\n"
        "   - 'answer': the full correct answer (for written) or a short "
        "explanation of why the option(s) are correct (for MCQ)\n"
        "   - 'marks': integer or null\n"
        "6. Return ONLY a JSON object shaped exactly like:\n"
        '{"questions": [{"number": 1, "topic": "...", "q_type": "single", '
        '"question": "...", "options": ["A) ...","B) ...","C) ...","D) ..."], '
        '"correct_options": ["B"], "answer": "...", "marks": 2}]}\n'
        "No text outside the JSON."
    )

    user = (
        f"Create exactly {spec['count']} questions.\n"
        f"Grade/Class: {spec['grade']}\n"
        f"Subject: {spec['subject']}\n"
        f"Topic focus: {spec.get('topic') or 'any suitable topics'}\n"
        f"Difficulty: {spec['difficulty']}\n"
        f"Assessment type: {spec['assessment_type']}\n"
        f"Question format: {fmt}\n\n"
        f"Reference material (for grounding only, do NOT copy):\n{grounding}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_questions(spec: dict, grounding: str) -> list[dict]:
    """Turn a completed spec + grounding into original questions with answers."""
    messages = build_generation_prompt(spec, grounding)

    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.8,
    )

    data = json.loads(resp.choices[0].message.content)
    return data.get("questions", [])


def generate_unique_set(spec: dict, grounding: str, set_tag: str) -> dict:
    """Generate questions that pass BOTH gates — well-formed (verification)
    AND non-repeating (uniqueness) — regenerating until the set is full
    or the safety cap is hit."""
    needed = spec["count"]
    collected = []
    attempts = 0

    while len(collected) < needed and attempts < config.MAX_GENERATION_ATTEMPTS:
        attempts += 1
        remaining = needed - len(collected)

        batch_spec = {**spec, "count": remaining}
        batch = generate_questions(batch_spec, grounding)

        # GATE 1 — verification (free): drop malformed questions first
        well_formed, flawed = verification.verify_batch(batch)

        # GATE 2 — uniqueness (costs a query): only on well-formed survivors
        unique, duplicates = uniqueness.filter_unique(
            well_formed, f"{set_tag}-a{attempts}"
        )

        collected.extend(unique)

        print(f"  Attempt {attempts}: asked {remaining}, "
              f"flawed {len(flawed)}, duplicate {len(duplicates)}, "
              f"kept {len(unique)} (total {len(collected)}/{needed})")

    for i, q in enumerate(collected[:needed], start=1):
        q["number"] = i

    return {
        "questions": collected[:needed],
        "requested": needed,
        "delivered": min(len(collected), needed),
        "attempts": attempts,
        "short": len(collected) < needed,
    }


if __name__ == "__main__":
    uniqueness.chroma_client.delete_collection("questions")
    uniqueness.collection = uniqueness.chroma_client.get_or_create_collection("questions")

    spec = {
        "grade": 8, "subject": "Maths", "topic": None,
        "count": 4, "difficulty": "medium", "assessment_type": "olympiad",
        "question_format": "mcq",
    }
    grounding = (
        "[Source 1] Class 8 Maths Olympiad: exponents and powers, algebraic "
        "expressions, mensuration, data handling, rational numbers."
    )

    result = generate_unique_set(spec, grounding, "mcqtest")

    for q in result["questions"]:
        marks = f"({q['marks']} marks)" if q.get("marks") is not None else ""
        print(f"\nQ{q['number']} [{q['q_type'].upper()}] {marks}")
        print(f"  {q['question']}")
        for opt in q.get("options", []):
            print(f"     {opt}")
        print(f"  Correct: {q.get('correct_options')}")
        print(f"  Why: {q['answer']}")