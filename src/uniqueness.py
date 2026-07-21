import chromadb
from src import config

# The specialized vault for meaning-signatures (persists to disk)
chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)

# One shelf inside it, holding all past question signatures
collection = chroma_client.get_or_create_collection(name="questions")


def is_duplicate(question_text: str) -> tuple[bool, float]:
    """Check a question's meaning against every past question.
    Returns (is_too_similar, closest_similarity_score)."""
    # If the vault is empty, nothing can be a duplicate yet
    if collection.count() == 0:
        return False, 0.0

    # Ask Chroma for the single closest past question by meaning
    result = collection.query(query_texts=[question_text], n_results=1)

    distances = result.get("distances", [[]])[0]
    if not distances:
        return False, 0.0

    # Chroma returns DISTANCE (0 = identical). Similarity = 1 - distance.
    similarity = 1 - distances[0]
    return similarity >= config.SIMILARITY_THRESHOLD, similarity


def remember_question(question_text: str, question_id: str) -> None:
    """Seal a question's meaning-signature into the vault so future
    questions get checked against it."""
    collection.add(documents=[question_text], ids=[question_id])


def filter_unique(questions: list[dict], set_tag: str) -> tuple[list, list]:
    """Split a fresh batch into (unique, rejected) by comparing each
    question against everything remembered so far — including earlier
    questions in this same batch."""
    unique = []
    rejected = []
    for q in questions:
        too_similar, score = is_duplicate(q["question"])
        if too_similar:
            rejected.append({"question": q["question"], "similarity": round(score, 3)})
        else:
            unique.append(q)
            # remember it immediately, so the NEXT question in this batch
            # also gets checked against it (catches in-batch twins too)
            q_id = f"{set_tag}-q{q['number']}"
            remember_question(q["question"], q_id)
    return unique, rejected


if __name__ == "__main__":
    # Start clean so the demo is honest
    try:
        chroma_client.delete_collection("questions")
    except Exception:
        pass
    collection = chroma_client.get_or_create_collection(name="questions")

    # 1) First question is always unique (empty vault)
    q1 = "If I have a pizza cut into two equal pieces and eat one, what fraction did I eat?"
    dup, score = is_duplicate(q1)
    print(f"Q1 duplicate? {dup} (score {score:.3f})")
    remember_question(q1, "demo-q1")

    # 2) Reworded pizza question — SAME meaning, different words. Should be caught.
    q2 = "A pizza is split into 2 equal slices; you eat one. What fraction have you eaten?"
    dup, score = is_duplicate(q2)
    print(f"Q2 (reworded pizza) duplicate? {dup} (score {score:.3f})")

    # 3) Genuinely different question. Should pass.
    q3 = "What is the capital of France?"
    dup, score = is_duplicate(q3)
    print(f"Q3 (unrelated) duplicate? {dup} (score {score:.3f})")