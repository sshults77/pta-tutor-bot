import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import os
import pdfplumber
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from pptx import Presentation
import openai
import json

# --- Load users from YAML ---
with open('users.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

# --- LOGIN ---
login_result = authenticator.login(location='main')
if login_result is None:
    st.stop()

if isinstance(login_result, tuple):
    if len(login_result) == 2:
        name, authentication_status = login_result
        username = getattr(authenticator, "username", None)
    elif len(login_result) == 3:
        name, authentication_status, username = login_result
    else:
        st.error("Unknown login return value structure.")
        st.stop()
else:
    st.error("Unexpected login return type.")
    st.stop()

if authentication_status is False:
    st.error("Username/password is incorrect")
    st.stop()
elif authentication_status is None:
    st.warning("Please enter your username and password")
    st.stop()

user_role = config['credentials']['usernames'][username]['role']
st.sidebar.write(f"Logged in as: **{name}** ({username})")
st.success("Login success! You now see the main app.")

# --- Main App ---
st.title("📚 PTA Tutor Chatbot with Quiz & Performance Tracker")

# ---- Course selection ----
base_course_dir = "course_materials"
courses = [
    d for d in os.listdir(base_course_dir)
    if os.path.isdir(os.path.join(base_course_dir, d))
    and not d.startswith('.')
]
courses.sort()
course = st.selectbox("Select your course:", courses)
course_folder = os.path.join(base_course_dir, course)

def load_pdf_text(folder):
    text = ""
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            if filename.endswith(".pdf"):
                file_path = os.path.join(folder, filename)
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text
    return text

pdf_text = load_pdf_text(course_folder)[:3000]

def load_txt_content(folder):
    txt_file = None
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                txt_file = os.path.join(folder, filename)
                break
    if txt_file:
        with open(txt_file, "r", encoding="utf-8") as f:
            return f.read()
    return ""

txt_text = load_txt_content(course_folder)[:3000]

def extract_notes_from_uploaded_pptx(uploaded_file):
    prs = Presentation(uploaded_file)
    all_notes = []
    for i, slide in enumerate(prs.slides):
        slide_title = slide.shapes.title.text if slide.shapes.title else f"Slide {i+1}"
        notes_text = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes_text = slide.notes_slide.notes_text_frame.text.strip()
        all_notes.append(f"{slide_title}:\n{notes_text}\n")
    return "\n".join(all_notes)

st.sidebar.header("Optional: Upload PowerPoint for Chatbot Content")
uploaded_pptx = st.sidebar.file_uploader("Upload a PowerPoint (.pptx)", type="pptx")
pptx_text = ""
if uploaded_pptx:
    pptx_text = extract_notes_from_uploaded_pptx(uploaded_pptx)
    st.sidebar.success("PowerPoint notes extracted. Chatbot will use these as course content.")

openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key

log_path = Path("grading_log.csv")
if not log_path.exists():
    pd.DataFrame(columns=[
        "username", "question_id", "question_text", "user_answer",
        "correct_answer", "correct", "timestamp", "topic", "blooms_level"
    ]).to_csv(log_path, index=False)

# --------- Instructor Dashboard with UI Controls -----------
if user_role == "admin":
    st.sidebar.header("🧑‍🏫 Instructor Dashboard")
    min_score = st.sidebar.slider("Flag students below this score (%)", 0, 100, 60)
    min_attempts = st.sidebar.number_input("Minimum questions attempted", 1, 50, 5)
    min_score_frac = min_score / 100

    try:
        df = pd.read_csv(log_path)
        summary = (
            df.groupby("username")["correct"]
            .agg(['mean', 'count'])
            .reset_index()
            .rename(columns={'mean': 'score', 'count': 'attempts'})
        )
        flagged = summary[(summary['score'] < min_score_frac) & (summary['attempts'] >= min_attempts)]
        st.markdown("### 🚩 Students Flagged as Struggling")
        st.dataframe(flagged, use_container_width=True)

        drill_user = st.selectbox("Drill down: select a student", [""] + list(flagged['username']))
        if drill_user:
            st.markdown(f"#### Details for `{drill_user}`")
            user_rows = df[df['username'] == drill_user]
            if 'topic' in user_rows.columns:
                st.markdown("**By Topic:**")
                st.dataframe(user_rows.groupby("topic")["correct"].mean().reset_index().rename(columns={"correct": "Score"}))
            if 'blooms_level' in user_rows.columns:
                st.markdown("**By Bloom's Level:**")
                st.dataframe(user_rows.groupby("blooms_level")["correct"].mean().reset_index().rename(columns={"correct": "Score"}))
            st.markdown("**Raw Results:**")
            st.dataframe(user_rows, use_container_width=True)

        csv = flagged.to_csv(index=False)
        st.download_button("Download flagged report CSV", csv, "flagged_students.csv", "text/csv")
    except Exception as e:
        st.error(f"Admin dashboard error: {e}")

# ------ Student main area ------
st.header("💬 Chat with the Tutor")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask a question about your course..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    if pptx_text:
        course_content = pptx_text
        content_source = "PowerPoint notes"
    elif txt_text:
        course_content = txt_text
        content_source = "Text file"
    else:
        course_content = pdf_text
        content_source = "PDF"

    st.info(f"Chatbot is using: {content_source}")

    system_prompt = {
        "role": "system",
        "content": f"""You are a knowledgeable and focused PTA tutor.

Use ONLY this course content to answer questions.

Do NOT reference slide numbers or slide locations in any answers or questions. Only focus on the content itself, not where it appears in the slides or documents.

{course_content}

If the question is unrelated to the material, respond: 'I'm sorry, I can only help with the course content provided.'"""
    }

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[system_prompt] + st.session_state.messages
        )
        reply = response.choices[0].message.content
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# --- Quiz Generator with Interactive Answer Collection ---
st.header("📝 Interactive Quiz Generator")

bloom_option = st.selectbox(
    "Choose Bloom's Taxonomy Level for Quiz:",
    [
        "1 (Recall/Knowledge)",
        "2 (Comprehension)",
        "3 (Application)",
        "4 (Analysis)",
        "5 (Synthesis/Evaluation)",
        "Mixed (Levels 1–5)"
    ]
)

if "quiz" not in st.session_state:
    st.session_state.quiz = None
if "quiz_answers" not in st.session_state:
    st.session_state.quiz_answers = {}

def parse_gpt_json(json_str):
    try:
        return json.loads(json_str)
    except Exception:
        # Try to recover from formatting issues
        import re
        try:
            cleaned = re.sub(r'```json|```', '', json_str, flags=re.IGNORECASE)
            return json.loads(cleaned)
        except Exception:
            return []

if st.button("Generate New Quiz"):
    if pptx_text:
        course_content = pptx_text
    elif txt_text:
        course_content = txt_text
    else:
        course_content = pdf_text

    blooms_level_map = {
        "1": "Recall/Knowledge",
        "2": "Comprehension",
        "3": "Application",
        "4": "Analysis",
        "5": "Synthesis/Evaluation"
    }

    if bloom_option.startswith("Mixed"):
        blooms_instruction = (
            "Generate 5 NPTE-style multiple-choice questions: "
            "one each at Bloom's Level 1 (Recall/Knowledge), "
            "Level 2 (Comprehension), Level 3 (Application), "
            "Level 4 (Analysis), and Level 5 (Synthesis/Evaluation). "
        )
    else:
        level = bloom_option[0]
        level_name = blooms_level_map.get(level, "")
        blooms_instruction = (
            f"Generate 5 NPTE-style multiple-choice questions at Bloom's Level {level} ({level_name}). "
        )

    quiz_prompt = (
        f"You are a Physical Therapist Assistant tutor. Based on the following course content, "
        f"{blooms_instruction}"
        "Do NOT reference slide numbers or slide locations in any questions. Focus only on content."
        "For each question: "
        "1) State the Bloom's Taxonomy level, "
        "2) Present the question in official NPTE exam style, "
        "3) Provide 4 answer options (A-D), "
        "4) List the correct answer after each question. "
        "Also include a field for the main topic/concept assessed. "
        "Respond ONLY in valid JSON as a list of objects with these keys: question, options, answer, rationale, topic, blooms_level."
        "Use only the provided material.\n\n"
        + course_content
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": quiz_prompt}]
        )
        quiz_json = response.choices[0].message.content
        quiz_data = parse_gpt_json(quiz_json)
        if not isinstance(quiz_data, list):
            st.error("Quiz format error.")
            quiz_data = []
        st.session_state.quiz = quiz_data
        st.session_state.quiz_answers = {}
    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")
        st.session_state.quiz = None

# ---- Render Quiz UI and collect answers ----
quiz = st.session_state.quiz
quiz_answers = st.session_state.quiz_answers
if quiz:
    st.markdown("### Answer the Quiz:")
    with st.form("quiz_form"):
        for idx, q in enumerate(quiz):
            st.markdown(f"**Q{idx+1}:** {q['question']}")
            selected = st.radio(
                f"Choose your answer for Q{idx+1}",
                q["options"],
                key=f"quiz_{idx}_answer"
            )
            quiz_answers[str(idx)] = selected
            st.markdown("---")
        submitted = st.form_submit_button("Submit Quiz")

    if submitted:
        feedback = []
        sample_log = []
        num_correct = 0

        for idx, q in enumerate(quiz):
            user_ans = quiz_answers.get(str(idx), None)
            correct_ans = q['answer']
            correct = int(user_ans == correct_ans)
            if correct:
                fb = f"✅ Q{idx+1} Correct!"
            else:
                fb = f"❌ Q{idx+1} Incorrect. Correct answer: {correct_ans}."
                fb += f"\n- Topic to review: **{q.get('topic','Unknown')}**\n- Rationale: {q.get('rationale','')}"
            feedback.append(fb)
            if correct:
                num_correct += 1

            # Save detailed log
            sample_log.append({
                "username": username,
                "question_id": f"Q{idx+1}",
                "question_text": q["question"],
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "correct": correct,
                "timestamp": datetime.now().isoformat(),
                "topic": q.get("topic", ""),
                "blooms_level": q.get("blooms_level", ""),
            })

        # Save results to CSV log
        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame(sample_log)], ignore_index=True)
        df.to_csv(log_path, index=False)

        # Show feedback summary
        st.markdown(f"## Your Score: {num_correct}/{len(quiz)}")
        st.markdown("---".join(feedback))

# --- Performance Summary ---
with st.expander("📊 Show Performance Summary", expanded=False):
    try:
        df = pd.read_csv(log_path)
        if user_role == "admin":
            user_df = df
        else:
            user_df = df[df["username"] == username]
        correct_total = user_df["correct"].sum()
        incorrect_total = len(user_df) - correct_total

        st.write(f"Total Questions Answered: {len(user_df)}")
        st.write(f"✅ Correct: {correct_total}")
        st.write(f"❌ Incorrect: {incorrect_total}")

        fig, ax = plt.subplots()
        ax.bar(["Correct", "Incorrect"], [correct_total, incorrect_total])
        ax.set_ylabel("Number of Responses")
        ax.set_title("Student Performance")
        st.pyplot(fig)

        if "topic" in user_df.columns:
            topic_stats = user_df.groupby("topic")["correct"].mean().reset_index()
            st.write("### By Topic")
            st.dataframe(topic_stats)
        if "blooms_level" in user_df.columns:
            bloom_stats = user_df.groupby("blooms_level")["correct"].mean().reset_index()
            st.write("### By Bloom's Level")
            st.dataframe(bloom_stats)

    except Exception as e:
        st.warning("⚠️ No grading data available or error reading log.")
        st.text(str(e))
