import json
from groq import Groq
from src import config
from src import search

client = Groq(api_key=config.GROQ_API_KEY)


def extract_details(prompt: str) -> dict:
    """Pull whatever fields the teacher already gave from their prompt."""
    system = (
        "You extract question-set details from a teacher's request. "
        "Return ONLY a JSON object with these keys: "
        "grade, subject, topic, count, difficulty, assessment_type, "
        "question_format. "
        "Use null for anything the teacher did not clearly state. "
        "count must be an integer or null. "
        "assessment_type must be one of: practice, homework, test, exam, "
        "olympiad, or null. "
        "difficulty must be one of: easy, medium, hard, mixed, or null. "
        "question_format must be one of: mcq, written, mixed, or null. "
        "Set question_format to 'mcq' if they mention MCQ, multiple choice, "
        "or options; 'written' if they mention written/subjective/long answer; "
        "'mixed' if they want both; null if unclear. "
        "Do not guess or invent values. No text outside the JSON."
    )
    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def next_missing_field(spec: dict) -> str | None:
    """Return the first required field still empty, or None if complete."""
    for field in config.REQUIRED_FIELDS:
        value = spec.get(field)
        if value in (None, "", "null"):
            if field == "topic":  # optional — 'any' is allowed
                continue
            return field
    return None


def ask_clarifying_question(original_prompt: str, spec: dict, field: str) -> str:
    """Generate a context-aware question for the missing field.

    Uses the original prompt so the wording fits the request — e.g. an
    olympiad prompt asks about olympiad level / chapters, not generic phrasing.
    """
    system = (
        "You are a helpful teaching assistant collecting details to build a "
        "question set. Ask ONE short, natural clarifying question to obtain the "
        "missing detail. Tailor it to the teacher's original request. "
        "Return only the question text, nothing else."
    )
    user = (
        f"Teacher's original request: {original_prompt}\n"
        f"Details gathered so far: {json.dumps(spec)}\n"
        f"Missing detail to ask about: {field} "
        f"({config.REQUIRED_FIELDS[field]})"
    )
    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content.strip()


def merge_answer(spec: dict, field: str, answer: str) -> tuple[dict, bool, str]:
    """Interpret and validate the answer. Returns (spec, accepted, error_msg)."""
    system = (
        f"The teacher was asked for '{field}'. Interpret their answer and return "
        f"ONLY a JSON object with the single key '{field}'. "
        "For count return an integer. "
        "For assessment_type use one of: practice, homework, test, exam, olympiad. "
        "For difficulty use one of: easy, medium, hard, mixed. "
        "For question_format use one of: mcq, written, mixed. "
        "If the answer does not make sense for this field, use null."
    )
    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": answer},
        ],
        response_format={"type": "json_object"},
    )
    update = json.loads(resp.choices[0].message.content)
    value = update.get(field)

    is_valid, error = validate_field(field, value)
    if not is_valid:
        return spec, False, error  # rejected — don't store anything

    spec[field] = value
    spec.setdefault("context_notes", []).append(answer)
    return spec, True, ""


def build_search_keywords(spec: dict, original_prompt: str = "") -> str:
    """Turn the completed spec into a focused web-search query for grounding."""
    parts = [
        original_prompt,
        f"class {spec.get('grade')}",
        str(spec.get("subject") or ""),
        str(spec.get("topic") or ""),
        " ".join(spec.get("context_notes", [])),  # raw answers: "olympiad", etc.
        "syllabus topics questions",
    ]
    text = " ".join(p for p in parts if p).strip()

    # Dedupe words while preserving order (avoids "maths maths")
    seen = set()
    words = []
    for word in text.split():
        key = word.lower()
        if key not in seen:
            seen.add(key)
            words.append(word)
    return " ".join(words)


def run_intake(prompt: str) -> dict:
    """Conversational intake with validation: re-asks a field until valid."""
    spec = extract_details(prompt)

    while True:
        field = next_missing_field(spec)
        if field is None:
            break
        question = ask_clarifying_question(prompt, spec, field)
        answer = input(f"\n{question}\n> ")
        spec, accepted, error = merge_answer(spec, field, answer)
        if not accepted:
            print(f"  ⚠️  {error}")

    return spec



def validate_field(field: str, value) -> tuple[bool, str]:
    """Check a merged value is sensible. Returns (is_valid, error_message)."""
    if value in (None, "", "null"):
        return False, "I didn't catch that."

    if field == "count":
        try:
            n = int(value)
        except (ValueError, TypeError):
            return False, "Please give a number."
        if not (config.MIN_COUNT <= n <= config.MAX_COUNT):
            return False, f"Please pick between {config.MIN_COUNT} and {config.MAX_COUNT}."
        return True, ""

    if field == "grade":
        try:
            g = int(value)
        except (ValueError, TypeError):
            return False, "Please give a grade number."
        if not (config.MIN_GRADE <= g <= config.MAX_GRADE):
            return False, f"Grade should be {config.MIN_GRADE}–{config.MAX_GRADE}."
        return True, ""

    if field == "difficulty":
        if str(value).lower() not in config.VALID_DIFFICULTIES:
            return False, "Please choose: easy, medium, hard, or mixed."
        return True, ""
    
    if field == "question_format":
        if str(value).lower() not in config.VALID_QUESTION_FORMATS:
            return False, "Please choose: mcq, written, or mixed."
        return True, ""

    if field == "assessment_type":
        if str(value).lower() not in config.VALID_ASSESSMENT_TYPES:
            return False, "Please choose: practice, homework, test, or exam."
        return True, ""

    if field == "subject":
        if len(str(value).strip()) < 2:
            return False, "Please give a subject name."
        return True, ""

    return True, ""


def is_plausible_request(prompt: str) -> bool:
    """A real request needs actual words, not a bare number or symbols.
    Rejects '8', '123', '!!!' — accepts 'maths for class 8 olympiad'."""
    letters = sum(char.isalpha() for char in prompt)
    return letters >= 2


if __name__ == "__main__":
    print("=== Test A: format stated in prompt ===")
    prompt_a = "Give me 5 MCQ maths questions for class 8 olympiad, hard"
    spec_a = extract_details(prompt_a)
    print("Extracted:", spec_a)
    print("First missing:", next_missing_field(spec_a))

    print("\n=== Test B: format NOT stated (should ask) ===")
    prompt_b = "Give me 5 maths questions for class 8 olympiad, hard"
    spec_b = extract_details(prompt_b)
    print("Extracted:", spec_b)
    field = next_missing_field(spec_b)
    print("First missing:", field)
    if field:
        print("Agent asks:", ask_clarifying_question(prompt_b, spec_b, field))