import os
from dotenv import load_dotenv

load_dotenv()

# --- API keys ---
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# --- Models ---
TEXT_MODEL = "llama-3.3-70b-versatile"

# --- Question-set requirements ---
# The details a complete request needs. The agent asks for any of these
# that the teacher didn't already provide, one at a time.
REQUIRED_FIELDS = {
    "grade": "which class/grade the questions are for",
    "subject": "the subject",
    "topic": "the specific topic or chapter (optional — 'any' is allowed)",
    "count": "how many questions",
    "difficulty": "difficulty level (easy, medium, hard, or mixed)",
    "assessment_type": "type: practice, homework, test, or exam",
    "question_format": "format: mcq, written, or mixed",
}

# When assessment_type is one of these, marks must be added per question.
MARKS_REQUIRED_TYPES = {"test", "exam", "homework"}

# --- Search ---
SEARCH_MAX_RESULTS = 5

# --- Validation rules ---
VALID_DIFFICULTIES = {"easy", "medium", "hard", "mixed"}
VALID_ASSESSMENT_TYPES = {"practice", "homework", "test", "exam"}
MIN_COUNT = 1
MAX_COUNT = 50
MIN_GRADE = 1
MAX_GRADE = 12

VALID_ASSESSMENT_TYPES = {"practice", "homework", "test", "exam", "olympiad"}

# When assessment_type is one of these, marks must be added per question.
MARKS_REQUIRED_TYPES = {"test", "exam", "olympiad"}


# --- Database ---
DB_PATH = "data/exam_ai.db"

# --- Uniqueness (semantic dedup) ---
CHROMA_PATH = "data/chroma"
SIMILARITY_THRESHOLD = 0.75   # >= this = "too similar", reject the question

# --- Generation retry loop ---
MAX_GENERATION_ATTEMPTS = 6   # safety cap so a narrow topic can't loop forever

# --- Output files ---
OUTPUT_DIR = "outputs"

# --- Question format ---
VALID_QUESTION_FORMATS = {"mcq", "written", "mixed"}

# --- MCQ marks guidance ---
# single-correct = base marks; multiple-correct = harder, worth more
MCQ_MULTIPLE_BONUS = 1   # multiple-correct gets +1 over single-correct

# --- Grading policy for multiple-correct MCQs ---
# Options: "partial" (marks per correct pick, no penalty),
#          "all_or_nothing" (must match exactly),
#          "partial_penalty" (correct picks add, wrong picks subtract)
MCQ_MULTIPLE_POLICY = "partial"

# --- Vision model (for handwritten / scanned sheets) ---
VISION_MODEL = "gemini-2.0-flash"