from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, ForeignKey, DateTime
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from src import config
from src import pdf_utils
import json

Base = declarative_base()
engine = create_engine(f"sqlite:///{config.DB_PATH}")
SessionLocal = sessionmaker(bind=engine)


class QuestionSet(Base):
    """One generated set — the 'mission record', now with a proper name."""
    __tablename__ = "question_sets"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    name = Column(String)              # "Class 2nd Maths (Fractions) set-1"
    set_number = Column(Integer)       # the running count for this topic combo
    answer_name = Column(String)       # "Answer sheet for ...set-1"

    grade = Column(Integer)
    subject = Column(String)
    topic = Column(String, nullable=True)
    difficulty = Column(String)
    assessment_type = Column(String)
    count = Column(Integer)
    q_type = Column(String, default="written")   # 'written', 'single', 'multiple'
    options_json = Column(Text, default="[]")     # the options list, sealed as JSON
    correct_json = Column(Text, default="[]")     # correct letters, sealed as JSON

    # File paths — filled in the NEXT step when we generate the PDFs
    question_pdf_path = Column(String, nullable=True)
    answer_pdf_path = Column(String, nullable=True)

    questions = relationship(
        "Question", back_populates="question_set",
        cascade="all, delete-orphan",
    )


class Question(Base):
    """One question + its sealed answer — belongs to a QuestionSet."""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    set_id = Column(Integer, ForeignKey("question_sets.id"))
    number = Column(Integer)
    topic = Column(String, nullable=True)
    question_text = Column(Text)
    answer_text = Column(Text)   # the sealed answer key — never shown to student
    q_type = Column(String, default="written")   # 'written', 'single', 'multiple'
    options_json = Column(Text, default="[]")     # options list, sealed as JSON
    correct_json = Column(Text, default="[]")     # correct letters, sealed as JSON
    marks = Column(Integer, nullable=True)

    question_set = relationship("QuestionSet", back_populates="questions")


def init_db():
    """Create the vault and its shelves if they don't exist yet."""
    Base.metadata.create_all(engine)


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 11 -> '11th'..."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def list_sets() -> list[dict]:
    """Lightweight list of every sealed set (id + name) — used for matching."""
    session = SessionLocal()
    try:
        rows = session.query(QuestionSet.id, QuestionSet.name).all()
        return [{"id": r.id, "name": r.name} for r in rows]
    finally:
        session.close()


def _build_set_name(grade, subject, topic, set_number: int) -> str:
    """Compose the human-readable registry name for a set."""
    base = f"Class {_ordinal(int(grade))} {str(subject).title()}"
    if topic and str(topic).lower() not in ("", "none", "any", "null"):
        base += f" ({str(topic).title()})"
    return f"{base} set-{set_number}"


def next_set_number(session, grade, subject, topic) -> int:
    """Count how many sets already exist for this exact topic combo, +1.
    This is what makes set-1, set-2, set-3 count up correctly."""
    existing = (
        session.query(QuestionSet)
        .filter(
            QuestionSet.grade == grade,
            QuestionSet.subject == subject,
            QuestionSet.topic == topic,
        )
        .count()
    )
    return existing + 1


def save_question_set(spec: dict, questions: list[dict]) -> int:
    """Seal a generated set (with its answer key + registry name)."""
    session = SessionLocal()
    try:
        set_number = next_set_number(
            session, spec["grade"], spec["subject"], spec.get("topic")
        )
        name = _build_set_name(
            spec["grade"], spec["subject"], spec.get("topic"), set_number
        )
        answer_name = f"Answer sheet for {name}"

        q_set = QuestionSet(
            name=name,
            set_number=set_number,
            answer_name=answer_name,
            grade=spec["grade"],
            subject=spec["subject"],
            topic=spec.get("topic"),
            difficulty=spec["difficulty"],
            assessment_type=spec["assessment_type"],
            count=spec["count"],
        )
        for q in questions:
            q_set.questions.append(Question(
                number=q["number"],
                topic=q.get("topic"),
                q_type=q.get("q_type", "written"),
                question_text=q["question"],
                answer_text=q["answer"],
                options_json=json.dumps(q.get("options", [])),      # seal list -> text
                correct_json=json.dumps(q.get("correct_options", [])),
                marks=q.get("marks"),
            ))
        session.add(q_set)
        session.commit()
        new_id = q_set.id
        return new_id
    finally:
        session.close()


def load_question_set(set_id: int) -> dict | None:
    """Retrieve a sealed set back out of the vault by its id."""
    session = SessionLocal()
    try:
        q_set = session.get(QuestionSet, set_id)
        if q_set is None:
            return None
        return {
            "id": q_set.id,
            "name": q_set.name,
            "answer_name": q_set.answer_name,
            "set_number": q_set.set_number,
            "created_at": q_set.created_at,
            "grade": q_set.grade,
            "subject": q_set.subject,
            "topic": q_set.topic,
            "difficulty": q_set.difficulty,
            "assessment_type": q_set.assessment_type,
            "questions": [
                {
                    "number": q.number,
                    "q_type": q.q_type,
                    "question": q.question_text,
                    "answer": q.answer_text,
                    "options": json.loads(q.options_json or "[]"),      # text -> list
                    "correct_options": json.loads(q.correct_json or "[]"),
                    "marks": q.marks,
                }
                for q in sorted(q_set.questions, key=lambda x: x.number)
            ],
        }
    finally:
        session.close()


def generate_and_link_pdfs(set_id: int) -> tuple[str, str]:
    """Create both PDFs for a sealed set and save their paths into the vault.
    Returns (question_pdf_path, answer_pdf_path)."""
    # Load the full set data (this is what the PDF maker needs)
    set_data = load_question_set(set_id)
    if set_data is None:
        raise ValueError(f"No question set with id {set_id}")

    # Make the two PDFs on disk
    q_path, a_path = pdf_utils.create_pdfs_for_set(set_data)

    # Record WHERE they live, back into the vault
    session = SessionLocal()
    try:
        q_set = session.get(QuestionSet, set_id)
        q_set.question_pdf_path = q_path
        q_set.answer_pdf_path = a_path
        session.commit()
    finally:
        session.close()

    return q_path, a_path


if __name__ == "__main__":
    from src.generator import generate_unique_set

    init_db()
    print("Vault ready.\n")

    spec = {
        "grade": 8, "subject": "Maths", "topic": None,
        "count": 4, "difficulty": "medium", "assessment_type": "olympiad",
        "question_format": "mcq",
    }
    grounding = (
        "[Source 1] Class 8 Maths Olympiad: exponents, algebraic expressions, "
        "mensuration, rational numbers."
    )

    result = generate_unique_set(spec, grounding, "dbmcq")
    print(f"Generated {result['delivered']} unique questions.\n")

    set_id = save_question_set(spec, result["questions"])
    print(f"Sealed as set id {set_id}")

    # Read back to PROVE options/correct survived the round-trip
    loaded = load_question_set(set_id)
    print(f"Name: {loaded['name']}\n")
    for q in loaded["questions"]:
        print(f"Q{q['number']} [{q['q_type']}] ({q['marks']} marks)")
        print(f"  {q['question']}")
        for opt in q["options"]:
            print(f"     {opt}")
        print(f"  Correct: {q['correct_options']}  (type: {type(q['correct_options']).__name__})")