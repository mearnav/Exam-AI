def check_question(q: dict) -> list[str]:
    """Run deterministic checks on ONE question.
    Returns a list of problems found (empty list = the question is clean)."""
    problems = []
    q_type = q.get("q_type", "written")
    options = q.get("options", [])
    correct = q.get("correct_options", [])

    # --- Checks that apply to every question ---
    if not q.get("question", "").strip():
        problems.append("empty question text")

    if not q.get("answer", "").strip():
        problems.append("missing answer/explanation")

    # --- Written questions should have NO options ---
    if q_type == "written":
        if options or correct:
            problems.append("written question should not have options")
        return problems   # nothing more to check for written

    # --- From here down: MCQ checks (single or multiple) ---
    if len(options) < 2:
        problems.append("MCQ needs at least 2 options")

    # Extract the letter from each option, e.g. "A) 4" -> "A"
    option_letters = []
    for opt in options:
        letter = opt.strip()[0:1].upper()
        option_letters.append(letter)

    # No duplicate option VALUES (catches the two '-3/8' options bug)
    values = [opt.split(")", 1)[-1].strip().lower() for opt in options]
    if len(set(values)) != len(values):
        problems.append("duplicate option values")

    # No option should contain '=' (catches leaked working like 'D) x = 8')
    for opt in options:
        if "=" in opt:
            problems.append(f"option looks like working (contains '='): {opt}")

    # Every correct letter must actually exist among the options
    for c in correct:
        if c.upper() not in option_letters:
            problems.append(f"correct letter '{c}' is not an option")

    # Type must match the number of correct answers
    if q_type == "single" and len(correct) != 1:
        problems.append(f"single-correct must have exactly 1 answer, has {len(correct)}")
    if q_type == "multiple" and len(correct) < 2:
        problems.append(f"multiple-correct must have 2+ answers, has {len(correct)}")

    return problems


def verify_batch(questions: list[dict]) -> tuple[list, list]:
    """Split a batch into (clean, flawed).
    Flawed items keep their list of problems for logging."""
    clean = []
    flawed = []
    for q in questions:
        problems = check_question(q)
        if problems:
            flawed.append({"question": q.get("question", ""), "problems": problems})
        else:
            clean.append(q)
    return clean, flawed


if __name__ == "__main__":
    test_questions = [
        # Clean single MCQ
        {"q_type": "single", "question": "What is 2^3?",
         "options": ["A) 4", "B) 6", "C) 8", "D) 10"],
         "correct_options": ["C"], "answer": "2*2*2 = 8"},

        # BAD: option D has leaked working ('=') AND duplicates A's value
        {"q_type": "single", "question": "What is -3/4 divided by 2?",
         "options": ["A) -3/8", "B) -3/2", "C) -1/2", "D) -3/4 * 1/2 = -3/8"],
         "correct_options": ["A"], "answer": "-3/8"},

        # BAD: labeled single but has two correct answers
        {"q_type": "single", "question": "Which are even?",
         "options": ["A) 2", "B) 3", "C) 4", "D) 5"],
         "correct_options": ["A", "C"], "answer": "2 and 4 are even"},

        # BAD: correct letter 'E' doesn't exist
        {"q_type": "single", "question": "Capital of France?",
         "options": ["A) Paris", "B) Rome", "C) Berlin", "D) Madrid"],
         "correct_options": ["E"], "answer": "Paris"},

        # Clean written question
        {"q_type": "written", "question": "Explain fractions.",
         "options": [], "correct_options": [], "answer": "A fraction is part of a whole."},
    ]

    clean, flawed = verify_batch(test_questions)
    print(f"Clean: {len(clean)}   Flawed: {len(flawed)}\n")
    for f in flawed:
        print(f"FLAWED: {f['question']}")
        for p in f["problems"]:
            print(f"   - {p}")
        print()