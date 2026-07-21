import json
from groq import Groq
from src import config, grading

client = Groq(api_key=config.GROQ_API_KEY)


def extract_questions_from_pdf(pdf_path: str) -> dict:
    """Read a teacher's uploaded question PDF and pull out its questions +
    what subject/grade/topic they seem to cover. Returns a summary dict."""
    text = grading.read_pdf_text(pdf_path)

    if not text or text.strip() == "__VISION_UNAVAILABLE__":
        return {"questions": [], "summary": "", "raw_text": ""}

    system = (
        "You are reading a teacher's question paper. Extract the questions and "
        "identify what they cover. Return ONLY JSON:\n"
        '{"grade": "<grade if visible, else null>", '
        '"subject": "<subject if identifiable, else null>", '
        '"topic": "<main topic/chapter if identifiable, else null>", '
        '"questions": ["question 1 text", "question 2 text", ...], '
        '"summary": "<one sentence describing what this paper covers>"}\n'
        "Extract the questions as written. No text outside the JSON."
    )

    resp = client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    data["raw_text"] = text
    return data


def build_grounding_from_questions(extracted: dict) -> str:
    """Turn a teacher's extracted questions into a grounding block the
    generator can use — as reference for STYLE and TOPIC, not to copy."""
    lines = ["[Teacher's own question paper — use as reference for style and "
             "topic. Generate NEW original questions in this style, do not copy.]"]
    if extracted.get("summary"):
        lines.append(f"Summary: {extracted['summary']}")
    for i, q in enumerate(extracted.get("questions", []), 1):
        lines.append(f"Example {i}: {q}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingestion <path-to-question-pdf>")
    else:
        extracted = extract_questions_from_pdf(sys.argv[1])
        print("--- Extracted from teacher's PDF ---")
        print(f"Grade:   {extracted.get('grade')}")
        print(f"Subject: {extracted.get('subject')}")
        print(f"Topic:   {extracted.get('topic')}")
        print(f"Summary: {extracted.get('summary')}")
        print(f"\nFound {len(extracted.get('questions', []))} questions:")
        for i, q in enumerate(extracted.get("questions", []), 1):
            print(f"  {i}. {q}")

        print("\n--- Grounding block that would feed the generator ---")
        print(build_grounding_from_questions(extracted))