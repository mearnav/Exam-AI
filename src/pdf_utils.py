import os
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from src import config
from reportlab.platypus import Image

def _mcq_instruction(q_type: str) -> str:
    """The 'how to answer' line shown under an MCQ, based on its type."""
    if q_type == "single":
        return "(Single correct — circle one option)"
    if q_type == "multiple":
        return "(Multiple correct — circle all that apply)"
    return ""

def _marks_label(marks: int) -> str:
    """'1 mark' vs '2 marks' — correct singular/plural."""
    unit = "mark" if marks == 1 else "marks"
    return f"{marks} {unit}"

def _safe_filename(name: str) -> str:
    """Turn a set name into a filesystem-safe filename.
    'Class 2nd Maths (Fractions) set-1' -> 'Class_2nd_Maths_Fractions_set-1'"""
    keep = [ch for ch in name if ch.isalnum() or ch in (" ", "-", "_")]
    return "".join(keep).strip().replace(" ", "_")


def _styles():
    """Define the look of each text type. Fresh each call so re-running is safe."""
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SetTitle", parent=styles["Title"],
                              fontSize=16, spaceAfter=6))
    styles.add(ParagraphStyle(name="Meta", parent=styles["Normal"],
                              fontSize=9, textColor="#555555", spaceAfter=2))
    styles.add(ParagraphStyle(name="QItem", parent=styles["Normal"],
                              fontSize=11, spaceBefore=10, leading=16))
    styles.add(ParagraphStyle(name="AItem", parent=styles["Normal"],
                              fontSize=10, spaceBefore=2, leftIndent=14,
                              textColor="#1a5c3a"))
    styles.add(ParagraphStyle(name="Instr", parent=styles["Normal"],
                              fontSize=9, textColor="#7a5c00", leftIndent=14,
                              spaceBefore=2, spaceAfter=2))
    styles.add(ParagraphStyle(name="Option", parent=styles["Normal"],
                              fontSize=10, leftIndent=24, spaceBefore=1))
    styles.add(ParagraphStyle(name="ScoreCorrect", parent=styles["Normal"],
                              fontSize=10, leftIndent=14, textColor="#1a7a3a",
                              spaceBefore=1))
    styles.add(ParagraphStyle(name="ScoreWrong", parent=styles["Normal"],
                              fontSize=10, leftIndent=14, textColor="#b32020",
                              spaceBefore=1))
    styles.add(ParagraphStyle(name="ScorePartial", parent=styles["Normal"],
                              fontSize=10, leftIndent=14, textColor="#9a6a00",
                              spaceBefore=1))
    styles.add(ParagraphStyle(name="TotalLine", parent=styles["Title"],
                              fontSize=14, spaceBefore=6, spaceAfter=10))
    styles.add(ParagraphStyle(name="PassageHeading", parent=styles["Normal"],
                              fontSize=11, spaceBefore=6, spaceAfter=4,
                              textColor="#1a3d6b", fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="PassageBody", parent=styles["Normal"],
                              fontSize=10.5, leading=15, spaceAfter=10,
                              leftIndent=6, rightIndent=6))
    return styles


def _header(set_data, styles, title_text, total_marks):
    """Shared top block: title, info line, divider."""
    date = set_data.get("created_at")
    date_str = date.strftime("%d %b %Y") if hasattr(date, "strftime") else str(date)
    topic = set_data.get("topic") or "—"

    story = [Paragraph(escape(title_text), styles["SetTitle"])]
    info = (f'Class {set_data.get("grade")} &nbsp;|&nbsp; {set_data.get("subject")} '
            f'&nbsp;|&nbsp; Topic: {escape(str(topic))} &nbsp;|&nbsp; '
            f'Difficulty: {set_data.get("difficulty")}')
    story.append(Paragraph(info, styles["Meta"]))

    tail = f"Date: {date_str}"
    if total_marks:
        tail = f"Total marks: {total_marks} &nbsp;|&nbsp; " + tail
    story.append(Paragraph(tail, styles["Meta"]))

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.7, color="#999999"))
    return story


def create_question_pdf(set_data: dict, output_path: str) -> str:
    """The STUDENT'S paper: questions + marks, blank space to answer. No answers."""
    styles = _styles()
    questions = set_data["questions"]
    total = sum(q["marks"] for q in questions if q.get("marks"))

    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=20*mm,
                            bottomMargin=20*mm, leftMargin=18*mm, rightMargin=18*mm)
    story = _header(set_data, styles, set_data["name"], total)

    # If this set has a reading passage, print it above the questions
    passage = set_data.get("passage")
    if passage:
        story.append(Paragraph("Reading Passage", styles["PassageHeading"]))
        # Split into paragraphs so it renders with proper spacing
        for para in passage.split("\n"):
            if para.strip():
                story.append(Paragraph(escape(para.strip()), styles["PassageBody"]))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.5, color="#cccccc"))
        story.append(Spacer(1, 6))

    for q in questions:
        marks = q.get("marks")
        marks_txt = f' &nbsp;&nbsp;<b>({_marks_label(marks)})</b>' if marks is not None else ""
        line = f'<b>Q{q["number"]})</b> {escape(q["question"])}{marks_txt}'
        story.append(Paragraph(line, styles["QItem"]))

        diagram_path = q.get("diagram_path")
        if diagram_path and os.path.exists(diagram_path):
            story.append(Spacer(1, 6))
            img = Image(diagram_path)
            img._restrictSize(400, 220)   # cap size so it fits the page
            img.hAlign = "LEFT"
            story.append(img)
            story.append(Spacer(1, 6))
        
        options = q.get("options", [])
        if options:
            # MCQ: print the instruction, then each option indented
            instr = _mcq_instruction(q.get("q_type", ""))
            if instr:
                story.append(Paragraph(f'<i>{instr}</i>', styles["Instr"]))
            for opt in options:
                story.append(Paragraph(escape(opt), styles["Option"]))
            story.append(Spacer(1, 10))
        else:
            # Written question: leave the uniform gap
            story.append(Spacer(1, 22))

    doc.build(story)
    return output_path


def create_answer_pdf(set_data: dict, output_path: str) -> str:
    """The TEACHER'S answer sheet: each question followed by its sealed answer."""
    styles = _styles()
    questions = set_data["questions"]
    total = sum(q["marks"] for q in questions if q.get("marks"))

    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=20*mm,
                            bottomMargin=20*mm, leftMargin=18*mm, rightMargin=18*mm)
    story = _header(set_data, styles, set_data["answer_name"], total)

    passage = set_data.get("passage")
    if passage:
        story.append(Paragraph("Reading Passage", styles["PassageHeading"]))
        for para in passage.split("\n"):
            if para.strip():
                story.append(Paragraph(escape(para.strip()), styles["PassageBody"]))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.5, color="#cccccc"))
        story.append(Spacer(1, 6))

    for q in questions:
        marks = q.get("marks")
        marks_txt = f' &nbsp;&nbsp;<b>({_marks_label(marks)})</b>' if marks is not None else ""
        qline = f'<b>Q{q["number"]})</b> {escape(q["question"])}{marks_txt}'
        story.append(Paragraph(qline, styles["QItem"]))

        options = q.get("options", [])
        if options:
            for opt in options:
                story.append(Paragraph(escape(opt), styles["Option"]))
            correct = ", ".join(q.get("correct_options", []))
            story.append(Paragraph(f'<b>Correct:</b> {escape(correct)}', styles["AItem"]))
            story.append(Paragraph(f'<b>Why:</b> {escape(q["answer"])}', styles["AItem"]))
        else:
            story.append(Paragraph(f'<b>Ans:</b> {escape(q["answer"])}', styles["AItem"]))

        # If this question is a map with numbered markers, list what each is
        map_key = q.get("map_answer_key")
        if map_key:
            pairs = ", ".join(f"{num} = {name}"
                              for num, name in sorted(map_key.items(),
                                                      key=lambda x: int(x[0])))
            story.append(Paragraph(f'<b>Map key:</b> {escape(pairs)}', styles["AItem"]))
            
    doc.build(story)
    return output_path


def create_pdfs_for_set(set_data: dict) -> tuple[str, str]:
    """Make BOTH PDFs, named by convention, and return their file paths."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    base = _safe_filename(set_data["name"])
    q_path = os.path.join(config.OUTPUT_DIR, f"{base}.pdf")
    a_path = os.path.join(config.OUTPUT_DIR, f"Answer_{base}.pdf")
    create_question_pdf(set_data, q_path)
    create_answer_pdf(set_data, a_path)
    return q_path, a_path

def create_scored_pdf(set_data: dict, report: dict, student_name: str,
                      output_path: str) -> str:
    """Build the graded verdict: each question with the student's answer,
    the correct answer, why, marks earned — colour-coded — plus a total."""
    styles = _styles()

    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=20*mm,
                            bottomMargin=20*mm, leftMargin=18*mm, rightMargin=18*mm)

    # Header + big total line at the top
    title = f"Graded: {set_data['name']}"
    story = _header(set_data, styles, title, report["total_possible"])
    story.append(Paragraph(
        f'Student: {escape(student_name)} &nbsp;&nbsp;|&nbsp;&nbsp; '
        f'Score: {report["total_scored"]} / {report["total_possible"]}',
        styles["TotalLine"]))

    # Index the questions by number so we can pair them with results
    q_by_num = {q["number"]: q for q in set_data["questions"]}

    for r in report["results"]:
        q = q_by_num[r["number"]]

        # The question line with marks earned / marks possible
        head = (f'<b>Q{r["number"]})</b> {escape(q["question"])} '
                f'&nbsp;&nbsp;<b>[{r["score"]} / {r["marks"]}]</b>')
        story.append(Paragraph(head, styles["QItem"]))

        # Show options for MCQs so the letters make sense
        for opt in q.get("options", []):
            story.append(Paragraph(escape(opt), styles["Option"]))

        # Pick the colour by outcome
        if r["score"] == r["marks"] and r["marks"] > 0:
            style = styles["ScoreCorrect"]
        elif r["score"] > 0:
            style = styles["ScorePartial"]
        else:
            style = styles["ScoreWrong"]

        # Format the student's response and the correct answer readably
        student_txt = _fmt_response(r["student_response"])
        correct_txt = ", ".join(r["correct"]) if r["correct"] else escape(q["answer"])

        story.append(Paragraph(
            f'<b>Student answered:</b> {escape(student_txt)} &nbsp;&nbsp; '
            f'<b>Correct:</b> {escape(correct_txt)} &nbsp;&nbsp; '
            f'<b>({r["note"]})</b>', style))
        story.append(Paragraph(f'<b>Why:</b> {escape(q["answer"])}', styles["AItem"]))
        story.append(Spacer(1, 8))

    if report["needs_review"]:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<i>Note: written questions are marked 0 pending manual review.</i>",
            styles["Instr"]))

    doc.build(story)
    return output_path


def _fmt_response(resp) -> str:
    """Make a student response printable whether it's a list (MCQ) or text."""
    if isinstance(resp, list):
        return ", ".join(resp) if resp else "(blank)"
    return str(resp) if str(resp).strip() else "(blank)"


if __name__ == "__main__":
    from datetime import datetime, timezone
    from src import diagrams
    import os

    # Generate a real diagram to embed
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    diag_path = os.path.join(config.OUTPUT_DIR, "pdftest_foodchain.png")
    diagrams.draw_food_chain(["Sun", "Grass", "Rabbit", "Fox"], diag_path)

    sample = {
        "name": "Class 7th Science (Diagrams) set-1",
        "answer_name": "Answer sheet for Class 7th Science (Diagrams) set-1",
        "grade": 7, "subject": "Science", "topic": "Diagrams",
        "difficulty": "easy", "assessment_type": "test",
        "created_at": datetime.now(timezone.utc),
        "questions": [
            {"number": 1, "q_type": "written",
             "question": "Study the food chain below and name the top predator.",
             "options": [], "correct_options": [],
             "diagram_path": diag_path,
             "answer": "The fox is the top predator.", "marks": 3},
            {"number": 2, "q_type": "written",
             "question": "Explain what a food chain shows.",
             "options": [], "correct_options": [],
             "answer": "It shows how energy passes from one organism to another.", "marks": 3},
        ],
    }
    q_path, a_path = create_pdfs_for_set(sample)
    print("Question paper:", q_path)
    print("Answer sheet: ", a_path)