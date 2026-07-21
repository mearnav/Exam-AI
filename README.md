# 📝 Exam AI

**An end-to-end AI system that generates original exam papers and automatically grades student answer sheets.**

Exam AI takes a teacher's plain-language request (*"10 MCQ maths questions for class 8 olympiad, hard"*), asks clarifying questions when details are missing, grounds itself in live web research, and produces a unique, syllabus-appropriate question paper — plus a matching answer key. When a student's answer sheet is uploaded, it reads it (typed **or** handwritten), matches it to the right paper, grades it against the stored key, and returns a detailed scored report.

🔗 **Live demo:** _add your Streamlit URL here_
💻 **Repository:** [github.com/mearnav/Exam-AI](https://github.com/mearnav/Exam-AI)

---

## Why this project

Setting exams is repetitive, and reusing questions risks copyright issues and predictability. Exam AI solves this with a full **retrieve-then-generate** pipeline: it uses real web sources only as *grounding* (to match a real syllabus's topics, style, and difficulty) and then writes **entirely original** questions — so output is accurate, on-syllabus, copyright-clean, and never repeated.

It was built to demonstrate a complete, production-shaped AI application spanning the techniques most relevant to modern AI engineering:

| Capability | How Exam AI uses it |
|---|---|
| **RAG** | Live web search (Tavily) grounds generation in real syllabus material; semantic vector search (ChromaDB) enforces question uniqueness |
| **LLMs** | Llama 3.3 (via Groq) for generation, clarification, answer extraction, and written-answer grading |
| **Multimodal input** | Google Gemini vision reads handwritten / scanned answer sheets, with graceful fallback under rate limits |
| **Agentic architecture** | A stateful agent detects missing details, asks context-aware clarifying questions one at a time, and validates every answer before proceeding |
| **Real-world integration** | Deployed Streamlit web app; file upload/download; PDF generation and parsing; persistent relational storage |

---

## Key features

- **Conversational, self-directing intake.** The agent reads a request, detects what's missing (count, difficulty, subject, grade, format, assessment type), and asks tailored follow-up questions — validating each answer and re-asking on invalid input.
- **Original, grounded question generation.** Questions are written fresh by the LLM, grounded in live web-retrieved syllabus context. There are **no hardcoded questions** anywhere in the pipeline.
- **Never repeats a question.** A semantic uniqueness engine embeds every generated question and rejects any that are too similar to previous ones — catching reworded duplicates (e.g. *"pizza cut in two"* vs *"pizza split into 2 slices"*), not just exact matches. The system regenerates until the set is genuinely unique.
- **Automatic quality verification.** A deterministic checker rejects malformed questions (leaked working in options, duplicate options, mislabeled MCQ types, phantom correct answers) before they reach a paper.
- **Full question-type support.** Written answers, single-correct MCQs, and multiple-correct MCQs — with per-type marks and clear on-paper instructions ("circle one" / "circle all that apply").
- **Automatic marking scheme.** Marks are attached per question for exams, tests, homework, and olympiads, and totalled on the paper.
- **Two-document output.** A clean question paper for the student and a separate answer key for the teacher.
- **Multimodal auto-grading.** Upload a student's sheet → the system matches it to the correct stored paper → extracts their answers (typed via a parser, handwritten via vision) → grades against the sealed key → returns a colour-coded scored report with per-question feedback and reasoning.
- **Fair, explainable grading.** MCQs are graded deterministically (100% reliable); written answers are judged by the LLM on *meaning* (rewarding correct understanding worded differently), with reasoning attached and flagged for teacher review.
- **Learn from a teacher's own paper.** Upload an existing question PDF and generate fresh, original questions in the same style and topics.

---

## Architecture

Exam AI is built as a set of single-responsibility modules coordinated by a Streamlit front end. Two flows — **creation** and **grading** — share the same storage and PDF layers.

```
                         ┌─────────────────────────┐
   Teacher request  ─▶   │  Agent  (intake)        │  clarify + validate
                         │  src/agent.py           │
                         └───────────┬─────────────┘
                                     ▼
                         ┌─────────────────────────┐
                         │  RAG grounding          │  live web search
                         │  src/search.py (Tavily) │
                         └───────────┬─────────────┘
                                     ▼
      ┌──────────────────────────────────────────────────────┐
      │  Generation loop  (src/generator.py)                 │
      │   • LLM writes original questions + answer key        │
      │   • Verification gate   (src/verification.py)         │
      │   • Uniqueness gate     (src/uniqueness.py, ChromaDB) │
      │   • regenerate until the set is clean & unique        │
      └───────────────────────┬──────────────────────────────┘
                              ▼
        ┌───────────────────────────────────┐     ┌──────────────────┐
        │  Storage (SQLAlchemy / SQLite)    │◀───▶│  PDF generation   │
        │  src/database.py                  │     │  src/pdf_utils.py │
        │  sets ↔ questions (1-to-many)     │     │  paper + key +    │
        └───────────────────────────────────┘     │  scored report    │
                              ▲                    └──────────────────┘
                              │
      ┌───────────────────────┴──────────────────────────────┐
      │  Grading flow  (src/grading.py)                      │
      │   upload → read (parser / Gemini vision)              │
      │   → match to stored set → extract answers             │
      │   → grade (MCQ deterministic, written via LLM)        │
      │   → scored report PDF                                 │
      └──────────────────────────────────────────────────────┘
```

**Design principles used throughout:**

- **Separation of concerns** — each module does one job (intake, search, generation, verification, uniqueness, storage, PDFs, grading, vision, ingestion), so failures are isolated and the system is easy to extend.
- **Cheap checks before expensive ones** — deterministic verification runs before semantic uniqueness; typed-text extraction is tried before the vision model.
- **Fail gracefully** — external dependencies (e.g. the vision model under free-tier limits) degrade with clear user messaging instead of crashing the app.
- **Answers stay sealed** — model answers are generated at creation time and stored separately; they never appear on the student's paper and are only used at grading.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web app | Streamlit |
| Text LLM | Llama 3.3 70B via **Groq** |
| Vision (multimodal) | **Google Gemini** |
| Web retrieval (RAG) | **Tavily** search API |
| Vector database | **ChromaDB** (semantic uniqueness) |
| Relational storage | **SQLAlchemy** + SQLite |
| PDF generation | **ReportLab** |
| PDF parsing | **pdfplumber**, **PyMuPDF** |

---

## How it works

### Creating a paper
1. The teacher describes what they want (or uploads their own question paper to base a new set on).
2. The agent asks for any missing details — one clarifying question at a time — and validates each answer.
3. The system searches the web for real syllabus context on the topic.
4. The LLM writes original questions and an answer key, grounded in that context.
5. Each question passes a verification gate and a semantic-uniqueness gate; anything malformed or repeated is regenerated.
6. The set is stored, and two PDFs are produced: a question paper and a separate answer key.

### Grading a sheet
1. The teacher uploads a student's answer sheet.
2. The system reads it — typed text directly, or handwriting via the vision model.
3. It matches the sheet to the correct stored paper by name.
4. It transcribes the student's answers (without ever seeing the key, so it records exactly what the student wrote).
5. It grades: MCQs by exact comparison to the stored key, written answers by an LLM judge that scores on meaning.
6. It returns a colour-coded scored report with per-question marks, the correct answers, and explanations.

---

## Running locally

```bash
# 1. Clone and enter the project
git clone https://github.com/mearnav/Exam-AI.git
cd Exam-AI

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your API keys to a .env file in the project root:
#    GROQ_API_KEY=...
#    GOOGLE_API_KEY=...
#    TAVILY_API_KEY=...

# 5. Run the app
python -m streamlit run app.py
```

All three APIs (Groq, Google AI Studio, Tavily) offer free tiers.

---

## Notes and design decisions

- **Storage.** The app uses SQLite for local persistence, where data is retained permanently. The public demo runs on Streamlit's ephemeral storage; production persistence would use a hosted Postgres database — a connection-string change, since the data layer is built on SQLAlchemy.
- **Handwriting recognition** works best on legible writing; reading very messy handwriting is a known limitation of current vision models. The feature degrades gracefully when the vision API is rate-limited, keeping typed-sheet grading fully functional.
- **Written-answer grading** is AI-assisted and flagged for teacher review — the system is designed to support the teacher's judgement, not replace it.
- **Grading integrity.** The answer-transcription step is deliberately isolated from the answer key and constrained to record only what a student actually marked — never to solve questions itself. A deterministic guard also detects unanswered question papers and declines to grade them, rather than producing a misleading score.

---

## Author

**Arnav Srivastava** — [LinkedIn](https://linkedin.com/in/mearnav) · [GitHub](https://github.com/mearnav) · [Portfolio](https://arnavsriportfolio.vercel.app/)
