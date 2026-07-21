import pdfplumber
from src import database
import json
from groq import Groq
from src import config


client = Groq(api_key=config.GROQ_API_KEY)

def read_pdf_text(pdf_path: str) -> str:
    """Read a sheet: try typed-text extraction first (fast, free). If the page
    has little or no extractable text, it's likely handwritten/scanned — fall
    back to the vision model."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    typed_text = "\n".join(parts).strip()

    # If typed extraction found real content, use it
    if len(typed_text) >= 20:
        return typed_text

    # Otherwise, summon vision to read the handwriting
    from src import vision
    return vision.read_handwritten_pdf(pdf_path)


def match_set(uploaded_text: str) -> dict | None:
    """Find which stored set an uploaded sheet belongs to, by locating the
    set name inside the sheet's text. Returns {id, name} or None."""
    sets = database.list_sets()
    if not sets:
        return None

    text_lower = uploaded_text.lower()

    # Tier 1 — exact: the full set name appears in the sheet
    for s in sets:
        if s["name"].lower() in text_lower:
            return s

    # Tier 2 — fuzzy: score each set by how many of its name-words appear
    best, best_score = None, 0.0
    for s in sets:
        words = [w for w in s["name"].lower().split() if len(w) > 2]
        if not words:
            continue
        hits = sum(1 for w in words if w in text_lower)
        score = hits / len(words)
        if score > best_score:
            best, best_score = s, score

    # Only accept a fuzzy match if we're reasonably confident
    if best and best_score >= 0.6:
        return best
    return None

def extract_student_answers(uploaded_text: str, question_set: dict) -> dict:
    """Read the student's messy sheet and pull out their answer for each
    question. IMPORTANT: the answer key is NOT given to the model here — it
    only sees the questions, so it records what the student wrote, not what
    is correct."""
    # Give the model ONLY the questions (no answers) so it can't 'fix' anything
    q_list = []
    for q in question_set["questions"]:
        entry = {"number": q["number"], "question": q["question"], "type": q["q_type"]}
        if q["options"]:
            entry["options"] = q["options"]
        q_list.append(entry)

    system = (
        "You transcribe a student's answer sheet. You are given the questions "
        "and the raw text of what the student wrote. For EACH question, record "
        "exactly what the student answered — do NOT correct, judge, or complete "
        "anything. If you cannot find the student's answer for a question, use "
        "an empty string.\n"
        "For MCQ questions, record the option letter(s) the student chose as a "
        "list, e.g. ['C'] or ['A','C'].\n"
        "For written questions, record the student's full written answer as text.\n"
        "Return ONLY JSON shaped like:\n"
        '{"answers": [{"number": 1, "response": ["C"]}, '
        '{"number": 2, "response": "the student\'s written text"}]}\n'
        "No text outside the JSON."
    )

    user = (
        f"Questions:\n{json.dumps(q_list, indent=2)}\n\n"
        f"Raw student sheet text:\n{uploaded_text}"
    )

    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0,   # transcription must be faithful, not creative
    )

    data = json.loads(resp.choices[0].message.content)
    # Turn the list into a lookup by question number for easy grading later
    return {a["number"]: a["response"] for a in data.get("answers", [])}

def _grade_single(student_resp, correct: list, marks: int) -> tuple[float, str]:
    """Single-correct MCQ: full marks if the one letter matches, else 0."""
    student = [s.upper() for s in student_resp] if isinstance(student_resp, list) else []
    if student and set(student) == {c.upper() for c in correct}:
        return marks, "correct"
    return 0, "incorrect"


def _grade_multiple(student_resp, correct: list, marks: int) -> tuple[float, str]:
    """Multiple-correct MCQ, scored by the configured policy."""
    student = {s.upper() for s in student_resp} if isinstance(student_resp, list) else set()
    correct_set = {c.upper() for c in correct}
    policy = config.MCQ_MULTIPLE_POLICY

    if policy == "all_or_nothing":
        return (marks, "correct") if student == correct_set else (0, "incorrect")

    per_option = marks / len(correct_set)          # equal share per correct answer
    right_picks = student & correct_set            # correct ones they chose
    wrong_picks = student - correct_set            # wrong ones they chose

    if policy == "partial_penalty":
        raw = per_option * (len(right_picks) - len(wrong_picks))
        score = max(0, raw)                        # never go below 0
    else:  # "partial" (no penalty) — your choice
        score = per_option * len(right_picks)

    score = round(score, 2)
    if score == marks:
        note = "fully correct"
    elif score > 0:
        note = f"partial ({len(right_picks)}/{len(correct_set)} correct picks)"
    else:
        note = "incorrect"
    return score, note


def grade_set(question_set: dict, student_answers: dict) -> dict:
    """Grade MCQs deterministically and written answers via the LLM judge.
    Written questions are flagged for teacher review. Returns per-question
    scores and a total."""
    results = []
    total_scored = 0.0
    total_possible = 0
    needs_review = False

    for q in question_set["questions"]:
        marks = q.get("marks") or 0
        total_possible += marks
        resp = student_answers.get(q["number"], "")

        if q["q_type"] == "single":
            score, note = _grade_single(resp, q["correct_options"], marks)
        elif q["q_type"] == "multiple":
            score, note = _grade_multiple(resp, q["correct_options"], marks)
        else:  # written — judged by the LLM (teacher can override)
            score, reason = grade_written_answer(
                q["question"], q["answer"], resp, marks
            )
            note = f"written (AI-graded) — {reason}"
            needs_review = True   # flag so teacher knows to double-check AI grading

        total_scored += score
        results.append({
            "number": q["number"],
            "q_type": q["q_type"],
            "marks": marks,
            "student_response": resp,
            "correct": q.get("correct_options", []),
            "score": score,
            "note": note,
        })

    return {
        "results": results,
        "total_scored": round(total_scored, 2),
        "total_possible": total_possible,
        "needs_review": needs_review,
    }

def grade_written_answer(question: str, model_answer: str,
                         student_answer: str, marks: int) -> tuple[float, str]:
    """Use the LLM as a fair judge for a written answer.
    Returns (score, reasoning). The teacher can always override."""
    if not student_answer or not str(student_answer).strip():
        return 0, "No answer given."

    system = (
        "You are a fair, consistent exam grader. You are given a question, the "
        "correct model answer, the marks available, and a student's answer. "
        "Award marks based on how well the student's answer matches the meaning "
        "and key points of the model answer — reward correct understanding even "
        "if worded differently. Do not require exact wording. Be fair but "
        "accurate. Partial credit is allowed for partially correct answers.\n"
        "Return ONLY JSON: {\"score\": <number>, \"reason\": \"<short "
        "explanation>\"}. The score must be between 0 and the marks available."
    )
    user = (
        f"Question: {question}\n"
        f"Model answer: {model_answer}\n"
        f"Marks available: {marks}\n"
        f"Student's answer: {student_answer}"
    )

    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0,   # same answer must always get the same grade
    )

    data = json.loads(resp.choices[0].message.content)
    score = data.get("score", 0)

    # Safety clamp: never let the judge award out-of-range marks
    try:
        score = float(score)
    except (ValueError, TypeError):
        score = 0
    score = max(0, min(score, marks))     # keep it within [0, marks]

    return round(score, 2), data.get("reason", "")


if __name__ == "__main__":
    # Quick focused test of written grading
    tests = [
        ("Explain why 1/2 is greater than 1/4.",
         "Halves are bigger pieces than quarters, so 1/2 > 1/4.",
         "a half is more than a quarter because the pieces are larger", 3),
        ("Explain why 1/2 is greater than 1/4.",
         "Halves are bigger pieces than quarters, so 1/2 > 1/4.",
         "1/4 is bigger than 1/2", 3),   # WRONG answer
        ("Explain why 1/2 is greater than 1/4.",
         "Halves are bigger pieces than quarters, so 1/2 > 1/4.",
         "", 3),                          # blank
    ]
    for q, model, student, marks in tests:
        score, reason = grade_written_answer(q, model, student, marks)
        print(f"\nStudent: '{student}'")
        print(f"  Score: {score}/{marks}")
        print(f"  Reason: {reason}")