import os
import tempfile
import streamlit as st
from src import database

st.set_page_config(page_title="Exam AI", page_icon="📝", layout="centered")

os.makedirs("data/chroma", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

database.init_db()   # ensure the vault + its tables exist on startup

st.title("📝 Exam AI")
st.caption("Generate original question sets and grade answer sheets — powered by RAG + LLMs.")

# Two tabs: one for creating question sets, one for grading uploads
tab_create, tab_grade = st.tabs(["Create Questions", "Grade Answers"])

with tab_create:
    st.header("Create a question set")

    # Session memory
    if "stage" not in st.session_state:
        st.session_state.stage = "start"
        st.session_state.prompt = ""
        st.session_state.spec = {}

    if st.button("Start over", key="reset_create"):
        for k in ("stage", "prompt", "spec", "created", "upload_grounding", "upload_meta"):
            st.session_state.pop(k, None)
        st.rerun()

    # STAGE 1: choose how to start — describe, or upload own questions
    if st.session_state.stage == "start":
        mode = st.radio(
            "How would you like to start?",
            ["Describe what I want", "Upload my own questions to generate similar ones"],
            key="create_mode",
        )

        if mode == "Describe what I want":
            prompt = st.text_input(
                "Describe the question set you want:",
                placeholder="e.g. 10 MCQ maths questions for class 8 olympiad, hard",
            )
            if st.button("Begin", key="begin") and prompt.strip():
                from src import agent
                if not agent.is_plausible_request(prompt):
                    st.warning("Please describe what you want (not just a number).")
                else:
                    st.session_state.prompt = prompt
                    st.session_state.spec = agent.extract_details(prompt)
                    st.session_state.stage = "clarifying"
                    st.rerun()

        else:  # Upload-your-own-questions path
            up = st.file_uploader("Upload your question paper (PDF)", type="pdf",
                                  key="own_q_upload")
            extra = st.text_input(
                "What should I do with it? (optional)",
                placeholder="e.g. make 10 similar questions on the same topics",
            )
            if up is not None and st.button("Read & continue", key="read_own"):
                from src import ingestion
                import os, tempfile
                tmp_dir = tempfile.mkdtemp()
                tmp_path = os.path.join(tmp_dir, "teacher_q.pdf")
                with open(tmp_path, "wb") as f:
                    f.write(up.getbuffer())

                with st.spinner("Reading your questions..."):
                    extracted = ingestion.extract_questions_from_pdf(tmp_path)
                os.remove(tmp_path)

                if not extracted.get("questions"):
                    st.error("Couldn't read questions from that PDF. Is it a typed question paper?")
                else:
                    st.session_state.upload_grounding = ingestion.build_grounding_from_questions(extracted)
                    st.session_state.upload_meta = extracted
                    # If the teacher gave an instruction, seed the prompt; else we'll ask
                    seed = extra.strip() if extra.strip() else (
                        f"make similar questions for class {extracted.get('grade')} "
                        f"{extracted.get('subject')}")
                    st.session_state.prompt = seed
                    from src import agent
                    st.session_state.spec = agent.extract_details(seed)
                    # pre-fill subject/grade/topic from the paper if the LLM found them
                    for key in ("grade", "subject", "topic"):
                        if not st.session_state.spec.get(key) and extracted.get(key):
                            st.session_state.spec[key] = extracted[key]
                    st.session_state.stage = "clarifying"
                    st.info(f"Read your paper: {extracted.get('summary','')}")
                    st.rerun()

    # STAGE 2: clarify missing details (shared by both paths)
    if st.session_state.stage == "clarifying":
        from src import agent
        field = agent.next_missing_field(st.session_state.spec)
        if field is None:
            st.session_state.stage = "generate"
            st.rerun()
        else:
            st.write(f"**Request so far:** {st.session_state.prompt}")
            question = agent.ask_clarifying_question(
                st.session_state.prompt, st.session_state.spec, field)
            answer = st.text_input(question, key=f"ans_{field}")
            if st.button("Submit answer", key=f"sub_{field}") and answer.strip():
                spec, accepted, error = agent.merge_answer(
                    st.session_state.spec, field, answer)
                st.session_state.spec = spec
                if not accepted:
                    st.warning(error)
                st.rerun()

    # STAGE 3: generate — uses upload grounding if present, else web search
    if st.session_state.stage == "generate":
        from src import agent, search, generator, database
        spec = st.session_state.spec

        with st.spinner("Generating questions and checking uniqueness..."):
            if st.session_state.get("upload_grounding"):
                grounding = st.session_state.upload_grounding      # teacher's own
            else:
                keywords = agent.build_search_keywords(spec, st.session_state.prompt)
                references = search.gather_reference(keywords)
                grounding = search.format_for_prompt(references)   # web search

            result = generator.generate_unique_set(spec, grounding, "app")
            set_id = database.save_question_set(spec, result["questions"])
            q_path, a_path = database.generate_and_link_pdfs(set_id)

        loaded = database.load_question_set(set_id)
        st.session_state.created = {
            "name": loaded["name"], "q_path": q_path, "a_path": a_path,
            "delivered": result["delivered"], "requested": result["requested"],
            "short": result["short"],
        }
        st.session_state.stage = "done"
        st.rerun()

    # STAGE 4: results
    if st.session_state.stage == "done" and "created" in st.session_state:
        c = st.session_state.created
        st.success(f"✅ Created: {c['name']}")
        if c["short"]:
            st.warning(f"Only {c['delivered']} of {c['requested']} unique questions "
                       f"were possible. Try broadening the topic or lowering the count.")
        col1, col2 = st.columns(2)
        with open(c["q_path"], "rb") as f:
            col1.download_button("⬇ Question paper", f,
                                 file_name=c["q_path"].split("/")[-1], key="dl_q")
        with open(c["a_path"], "rb") as f:
            col2.download_button("⬇ Answer sheet", f,
                                 file_name=c["a_path"].split("/")[-1], key="dl_a")
        st.info("Use **Start over** above to make another set.")

with tab_grade:
    st.header("Grade an answer sheet")
    st.write("Upload a student's answer sheet (typed PDF) to grade it automatically.")

    uploaded = st.file_uploader("Student answer sheet (PDF)", type="pdf", key="grade_upload")

    if uploaded is not None and st.button("Grade it", key="do_grade"):
        from src import grading, database, pdf_utils, config

        # Write the upload to a TEMP file (used, then deleted — never stored)
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, "uploaded.pdf")
        with open(tmp_path, "wb") as f:
            f.write(uploaded.getbuffer())

        with st.spinner("Reading sheet, matching set, grading..."):
            text = grading.read_pdf_text(tmp_path)
            matched = grading.match_set(text)
        os.remove(tmp_path)   # discard the student's file immediately

        if grading.looks_like_blank_paper(text):
            st.warning(
                "This looks like a blank **question paper**, not a filled-in "
                "answer sheet. Please upload a sheet with the student's actual "
                "answers marked or written on it."
            )
            st.stop()

        if text.strip() == "__VISION_UNAVAILABLE__":
            st.warning(
                "This looks like a handwritten or scanned sheet, and the "
                "handwriting reader is temporarily unavailable (free-tier limit). "
                "Please try again later, or upload a typed PDF."
            )
            st.stop()
        if not text.strip():
            st.error("Couldn't read any text from this file. Is it a valid PDF?")
            st.stop()

        if matched is None:
            st.error(
                "Couldn't confidently match this sheet to a stored question set. "
                "Make sure the set name is written at the top of the answer sheet."
            )
        else:
            with st.spinner("Extracting answers and scoring..."):
                full_set = database.load_question_set(matched["id"])
                student_answers = grading.extract_student_answers(text, full_set)
                report = grading.grade_set(full_set, student_answers)

                student_name = "Student"
                scored_path = os.path.join(config.OUTPUT_DIR, f"scored_set{matched['id']}.pdf")
                pdf_utils.create_scored_pdf(full_set, report, student_name, scored_path)

            st.success(f"Matched to: {matched['name']}")
            st.metric("Score", f"{report['total_scored']} / {report['total_possible']}")

            if report["needs_review"]:
                st.warning("Some written questions were not auto-graded and need manual review.")

            for r in report["results"]:
                icon = "✅" if r["score"] == r["marks"] and r["marks"] > 0 else (
                       "🟡" if r["score"] > 0 else "❌")
                st.write(
                    f"{icon} **Q{r['number']}** — {r['score']}/{r['marks']} "
                    f"(you: {r['student_response']}, correct: {r['correct']})"
                )

            with open(scored_path, "rb") as f:
                st.download_button("⬇ Download scored report", f,
                                   file_name=scored_path.split("/")[-1],
                                   key="dl_scored")