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

    topic = spec.get("topic")
    if topic and str(topic).lower() not in ("", "none", "any", "null"):
        topic_rule = (
            f"IMPORTANT: Every question MUST be strictly about the topic "
            f"'{topic}'. Do not include questions from any other topic. "
            f"If the subject is Maths and the topic is 'Algebra', ask only "
            f"algebra questions (equations, expressions, factoring, etc.) — "
            f"not geometry, arithmetic, or other areas."
        )
    else:
        topic_rule = "Cover a suitable range of topics for the subject and grade."

    user = (
        f"Create exactly {spec['count']} questions.\n"
        f"Grade/Class: {spec['grade']}\n"
        f"Subject: {spec['subject']}\n"
        f"Difficulty: {spec['difficulty']}\n"
        f"Assessment type: {spec['assessment_type']}\n"
        f"Question format: {spec.get('question_format', 'written')}\n"
        f"{topic_rule}\n\n"
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


def generate_passage(spec: dict, word_count: int = 200) -> str:
    """Generate an original reading-comprehension passage for the given spec.
    The passage is what the comprehension questions will be based on."""
    system = (
        "You are an expert writer creating an ORIGINAL reading-comprehension "
        "passage for students. Rules:\n"
        "1. Write a single original passage — never copy existing text.\n"
        "2. Match the reading level to the given grade exactly.\n"
        "3. The passage must be self-contained and factually coherent, so "
        "questions can be asked about it.\n"
        f"4. Aim for about {word_count} words.\n"
        "Return ONLY the passage text — no title, no questions, no commentary."
    )
    user = (
        f"Grade/Class: {spec['grade']}\n"
        f"Subject: {spec['subject']}\n"
        f"Topic/theme: {spec.get('topic') or 'an age-appropriate general topic'}\n"
        f"Difficulty: {spec['difficulty']}\n"
        f"Write the passage now (~{word_count} words)."
    )
    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.8,
    )
    return resp.choices[0].message.content.strip()

def generate_passage_questions(spec: dict, passage: str) -> list[dict]:
    """Generate comprehension questions answerable ONLY from the given passage,
    each with its answer key. Questions are tied to this exact passage."""
    needs_marks = spec.get("assessment_type") in config.MARKS_REQUIRED_TYPES
    marks_rule = (
        "Assign a 'marks' value (integer) to each question based on difficulty."
        if needs_marks else "Set 'marks' to null for every question."
    )

    system = (
        "You are an expert exam setter writing reading-comprehension questions "
        "about a SPECIFIC passage the student will be given.\n"
        "Rules:\n"
        "1. Every question must be answerable ONLY from the passage provided. "
        "Do not ask about anything not stated in the passage.\n"
        "2. Write the correct answer for each question, drawn from the passage.\n"
        f"3. {marks_rule}\n"
        "4. These are written-answer comprehension questions: set 'q_type' to "
        "'written', 'options' to [], and 'correct_options' to [] for each.\n"
        "5. Return ONLY JSON shaped exactly like:\n"
        '{"questions": [{"number": 1, "topic": "comprehension", '
        '"q_type": "written", "question": "...", "options": [], '
        '"correct_options": [], "answer": "...", "marks": 2}]}\n'
        "No text outside the JSON."
    )
    user = (
        f"Create exactly {spec['count']} comprehension questions.\n"
        f"Grade/Class: {spec['grade']}\n"
        f"Difficulty: {spec['difficulty']}\n\n"
        f"PASSAGE:\n{passage}"
    )

    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("questions", [])


def is_comprehension(spec: dict) -> bool:
    """Detect whether this request is a reading-comprehension set."""
    fields = f"{spec.get('subject','')} {spec.get('topic','')}".lower()
    return "comprehension" in fields


def generate_set_with_passage(spec: dict, grounding: str, set_tag: str) -> dict:
    """Top-level generation: comprehension -> passage; diagram -> diagrams;
    otherwise the normal unique-set pipeline."""
    if is_comprehension(spec):
        passage = generate_passage(spec, word_count=spec.get("word_count", 200))
        questions = generate_passage_questions(spec, passage)
        for i, q in enumerate(questions, start=1):
            q["number"] = i
        return {"questions": questions, "requested": spec["count"],
                "delivered": len(questions), "attempts": 1,
                "short": len(questions) < spec["count"], "passage": passage}
    # If it's a diagram set, use the diagram-aware question generator
    if is_diagram_set(spec):
        questions = generate_diagram_questions(spec, grounding)
        for i, q in enumerate(questions, start=1):
            q["number"] = i
        questions = attach_diagrams(questions, set_tag, spec.get("subject", ""))
        return {"questions": questions, "requested": spec["count"],
                "delivered": len(questions), "attempts": 1,
                "short": len(questions) < spec["count"], "passage": None}

    # If it's a map set, generate questions then attach labeling maps
    if is_map_set(spec):
        questions = generate_diagram_questions(spec, grounding)  # reuse: written Qs
        for i, q in enumerate(questions, start=1):
            q["number"] = i
        questions = attach_maps(questions, set_tag)
        return {"questions": questions, "requested": spec["count"],
                "delivered": len(questions), "attempts": 1,
                "short": len(questions) < spec["count"], "passage": None}

    result = generate_unique_set(spec, grounding, set_tag)
    result["passage"] = None
    return result

def is_diagram_set(spec: dict) -> bool:
    """Detect whether this request is a diagram-based set."""
    fields = f"{spec.get('subject','')} {spec.get('topic','')}".lower()
    return "diagram" in fields


def attach_diagrams(questions: list[dict], set_tag: str, subject: str = "") -> list[dict]:
    """For a diagram set, generate a diagram (or blank space) per question."""
    import os
    from src import diagrams
    for q in questions:
        plan = diagrams.plan_diagram(q["question"], subject)   # <-- pass subject
        if plan["type"] == "none":
            q["diagram_path"] = None
            continue
        out_path = os.path.join(config.OUTPUT_DIR, f"diagram_{set_tag}_q{q['number']}.png")
        q["diagram_path"] = diagrams.render_diagram_for_question(plan, out_path)
    return questions

def generate_diagram_questions(spec: dict, grounding: str) -> list[dict]:
    """Generate questions for a diagram set that are ALWAYS answerable given
    what our diagram engine can produce. Key rule: never ask a student to
    'label a provided diagram' of something we can't draw — because we can't
    supply it. Complex topics must be 'draw and label' (student draws)."""
    needs_marks = spec.get("assessment_type") in config.MARKS_REQUIRED_TYPES
    marks_rule = (
        "Assign a 'marks' value (integer) per question based on difficulty."
        if needs_marks else "Set 'marks' to null for every question."
    )
    system = (
        "You are an exam setter creating ORIGINAL diagram-based questions.\n"
        "CRITICAL rules about diagrams:\n"
        "1. The system can accurately draw ONLY two things: linear food chains "
        "and simple cycles (like the water cycle). For these, you may ask the "
        "student to study/label the provided diagram.\n"
        "2. For ANY other diagram (anatomy, organs, plant/flower parts, cell "
        "structure, apparatus, etc.), the system CANNOT provide a pre-drawn "
        "diagram. So you MUST phrase these as 'Draw and label ...' so the "
        "student draws it themselves. NEVER write 'Label the given/provided "
        "diagram of X' for these — no diagram will exist for them to label.\n"
        "3. Prefer a mix: some 'draw and label' questions, some food-chain or "
        "cycle questions, and optionally plain written questions.\n"
        "4. Write all questions and answers in plain text (no LaTeX).\n"
        f"5. {marks_rule}\n"
        "6. Each question is written-answer: q_type 'written', options [], "
        "correct_options [].\n"
        "Return ONLY JSON:\n"
        '{"questions": [{"number": 1, "topic": "...", "q_type": "written", '
        '"question": "...", "options": [], "correct_options": [], '
        '"answer": "...", "marks": 2}]}\n'
        "No text outside the JSON."
    )
    user = (
        f"Create exactly {spec['count']} diagram-based questions.\n"
        f"Grade/Class: {spec['grade']}\nSubject: {spec['subject']}\n"
        f"Topic: {spec.get('topic') or 'general diagrams'}\n"
        f"Difficulty: {spec['difficulty']}\n\n"
        f"Reference (grounding only, do not copy):\n{grounding}"
    )
    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("questions", [])


def is_map_set(spec: dict) -> bool:
    """Detect whether this is a map-labeling set."""
    fields = f"{spec.get('subject','')} {spec.get('topic','')}".lower()
    return "map" in fields


def attach_maps(questions: list[dict], set_tag: str) -> list[dict]:
    """For a map set, generate a labeling map per question and attach its path
    plus the answer key (what each numbered marker is)."""
    import os
    from src import maps
    for q in questions:
        plan = maps.plan_map(q["question"])
        if not plan["markers"] or not plan["country"]:
            q["diagram_path"] = None
            continue
        out_path = os.path.join(config.OUTPUT_DIR, f"map_{set_tag}_q{q['number']}.png")
        path = maps.draw_labeling_map(plan["country"], plan["markers"], out_path)
        q["diagram_path"] = path
        # store the answer key for the markers (number -> location)
        q["map_answer_key"] = {str(i): m["label"]
                               for i, m in enumerate(plan["markers"], start=1)}
    return questions


if __name__ == "__main__":
    sample_spec = {
        "grade": 5, "subject": "English", "topic": "Comprehension",
        "count": 3, "difficulty": "hard", "assessment_type": "test",
        "question_format": "written",
    }
    passage = generate_passage(sample_spec, word_count=200)
    print("--- PASSAGE ---\n")
    print(passage)

    print("\n--- QUESTIONS ABOUT THIS PASSAGE ---")
    questions = generate_passage_questions(sample_spec, passage)
    for q in questions:
        marks = f"({q['marks']} marks)" if q.get("marks") is not None else ""
        print(f"\nQ{q['number']}) {q['question']} {marks}")
        print(f"   Answer: {q['answer']}")