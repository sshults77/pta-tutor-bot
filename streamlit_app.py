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
import re

# ---------- AUTHENTICATION AND CONFIGURATION ----------

# Load users and settings from YAML file
with open('users.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

# Authenticate user
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

login_result = authenticator.login(location='main')
if login_result is None:
    st.stop()

# Parse login result (2-tuple or 3-tuple)
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

# ---------- COURSE & CONTENT LOADING ----------

st.title("📚 PTA Tutor Chatbot with Quiz & Performance Tracker")

# Dynamically discover courses from course_materials directory
COURSE_MATERIALS_ROOT = "course_materials"
courses = [d for d in os.listdir(COURSE_MATERIALS_ROOT)
           if os.path.isdir(os.path.join(COURSE_MATERIALS_ROOT, d))]
if not courses:
    courses = ["PTA_1010"]

course = st.selectbox("Select your course:", sorted(courses))
course_folder = os.path.join(COURSE_MATERIALS_ROOT, course)

def load_pdf_text(folder):
    """Load and concatenate all PDF text from a folder."""
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

def load_txt_content(folder):
    """Load the first TXT file's contents from a folder."""
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

def extract_notes_from_uploaded_pptx(uploaded_file):
    """Extract all notes from an uploaded PowerPoint file."""
    prs = Presentation(uploaded_file)
    all_notes = []
    for i, slide in enumerate(prs.slides):
        slide_title = slide.shapes.title.text if slide.shapes.title else f"Slide {i+1}"
        notes_text = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes_text = slide.notes_slide.notes_text_frame.text.strip()
        all_notes.append(f"{slide_title}:\n{notes_text}\n")
    return "\n".join(all_notes)

# Load content from PDF, TXT, or PPTX
pdf_text = load_pdf_text(course_folder)[:3000]
txt_text = load_txt_content(course_folder)[:3000]

st.sidebar.header("Optional: Upload PowerPoint for Chatbot Content")
uploaded_pptx = st.sidebar.file_uploader("Upload a PowerPoint (.pptx)", type="pptx")
pptx_text = ""
if uploaded_pptx:
    pptx_text = extract_notes_from_uploaded_pptx(uploaded_pptx)
    st.sidebar.success("PowerPoint notes extracted. Chatbot will use these as course content.")

# ---------- OPENAI API SETUP ----------
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key

# ---------- LOGGING ----------
log_path = Path("grading_log.csv")
if not log_path.exists():
    pd.DataFrame(columns=[
        "username", "question_id", "question_text", "user_answer",
        "correct_answer", "correct", "topic", "blooms_level", "timestamp"
    ]).to_csv(log_path, index=False)

# ---------- CHATBOT (GPT) TUTOR ----------
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

    # Decide what content to use
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
        "content": (
            "You are a knowledgeable and focused PTA tutor.\n"
            "Use ONLY this course content to answer questions.\n"
            "Do NOT reference slide numbers or slide locations in any answers or questions. "
            "Only focus on the content itself, not where it appears in the slides or documents.\n\n"
            f"{course_content}\n\n"
            "If the question is unrelated to the material, respond: 'I'm sorry, I can only help with the course content provided.'"
        )
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

# ---------- QUIZ GENERATOR WITH REAL ANSWER COLLECTION ----------
st.header("📝 Quiz Generator")

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

# Helper function to parse GPT quiz JSON
def parse_gpt_quiz_json(gpt_json):
    """
    Expects a JSON string like:
    [
      {"id": "Q1", "question": "...", "options": {"A":"...",...}, "answer": "B", "explanation": "...", "topic": "...", "blooms_level": "2"},
      ...
    ]
    """
    try:
        questions = json.loads(gpt_json)
        assert isinstance(questions, list)
        for q in questions:
            assert "question" in q and "options" in q and "answer" in q
        return questions
    except Exception as e:
        st.error(f"Quiz parsing error: {e}")
        return None

# Main quiz interface
if "quiz_questions" not in st.session_state:
    st.session_state.quiz_questions = None
    st.session_state.quiz_answers = {}

def clear_quiz_state():
    st.session_state.quiz_questions = None
    st.session_state.quiz_answers = {}

if st.button("Generate Quiz"):
    clear_quiz_state()
    # Decide what content to use
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
            "Generate 5 NPTE-style multiple-choice questions in strict JSON format (see below):\n"
            "- One each at Bloom's Level 1 (Recall/Knowledge), Level 2 (Comprehension), "
            "Level 3 (Application), Level 4 (Analysis), and Level 5 (Synthesis/Evaluation).\n"
        )
    else:
        level = bloom_option[0]
        level_name = blooms_level_map.get(level, "")
        blooms_instruction = (
            f"Generate 5 NPTE-style multiple-choice questions at Bloom's Level {level} ({level_name}) "
            "in strict JSON format (see below):\n"
        )

    quiz_json_example = '''
[
  {
    "id": "Q1",
    "question": "What is the primary muscle responsible for knee extension?",
    "options": {
      "A": "Quadriceps femoris",
      "B": "Biceps femoris",
      "C": "Gastrocnemius",
      "D": "Tibialis anterior"
    },
    "answer": "A",
    "explanation": "The quadriceps femoris is responsible for knee extension.",
    "topic": "Knee Anatomy",
    "blooms_level": "1"
  }
  // 4 more in this format
]
    '''

    quiz_prompt = (
        "You are a Physical Therapist Assistant tutor. "
        "Based on the following course content, "
        f"{blooms_instruction}"
        "For each question:\n"
        "1) Output a valid JSON array of 5 objects.\n"
        "2) Each object has keys: id, question, options (dict), answer (letter), explanation, topic, blooms_level.\n"
        "3) Do NOT include slide numbers or references.\n"
        "Here is an example:\n"
        f"{quiz_json_example}\n"
        "Course content:\n"
        f"{course_content}"
    )

    # Call GPT for quiz JSON
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": quiz_prompt}]
        )
        # Extract the first code block, or use all content if not present
        raw = response.choices[0].message.content
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        gpt_json = match.group(1) if match else raw
        questions = parse_gpt_quiz_json(gpt_json)
        if questions:
            st.session_state.quiz_questions = questions
            st.session_state.quiz_answers = {}
    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")

# Render quiz and collect answers
if st.session_state.quiz_questions:
    st.markdown("### 📝 Answer Each Question:")
    with st.form("quiz_form"):
        for q in st.session_state.quiz_questions:
            st.write(f"**{q['id']}** ({q['topic']}, Bloom's Level: {q['blooms_level']})")
            st.write(q["question"])
            st.session_state.quiz_answers[q['id']] = st.radio(
                "Select your answer:",
                options=list(q["options"].keys()),
                format_func=lambda x: f"{x}: {q['options'][x]}",
                key=q["id"]
            )
            st.write("---")
        submitted = st.form_submit_button("Submit Answers")

    if submitted:
        # Grading and logging
        correct_count = 0
        records = []
        for q in st.session_state.quiz_questions:
            user_ans = st.session_state.quiz_answers.get(q['id'])
            correct = int(user_ans == q['answer'])
            if correct:
                correct_count += 1
            records.append({
                "username": username,
                "question_id": q["id"],
                "question_text": q["question"],
                "user_answer": user_ans,
                "correct_answer": q["answer"],
                "correct": correct,
                "topic": q.get("topic", ""),
                "blooms_level": q.get("blooms_level", ""),
                "timestamp": datetime.now().isoformat()
            })
        # Append to log
        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame(records)], ignore_index=True)
        df.to_csv(log_path, index=False)
        # Feedback
        st.success(f"You scored {correct_count} out of {len(st.session_state.quiz_questions)}.")
        st.markdown("#### Correct Answers & Explanations:")
        for q in st.session_state.quiz_questions:
            user_ans = st.session_state.quiz_answers.get(q['id'])
            if user_ans == q['answer']:
                st.write(f"**{q['id']}** ✅ Correct")
            else:
                st.write(f"**{q['id']}** ❌ Incorrect")
            st.write(f"Q: {q['question']}")
            st.write(f"Your answer: {user_ans} — Correct answer: {q['answer']} ({q['options'][q['answer']]})")
            st.write(f"Explanation: {q['explanation']}")
            st.write("---")
        # Clear quiz after submission
        clear_quiz_state()

# ---------- INSTRUCTOR DASHBOARD (Admin only) ----------
if user_role == "admin":
    st.header("📊 Instructor Dashboard: Flagged/Struggling Students")
    st.markdown("Use controls below to adjust the criteria for flagging students.")

    min_score_frac = st.slider("Minimum score for NOT being flagged (as a fraction)", 0.0, 1.0, 0.7, 0.05)
    min_attempts = st.number_input("Minimum number of quiz attempts to be considered", 1, 20, 3, 1)

    try:
        df = pd.read_csv(log_path)
        if df.empty or "username" not in df.columns or df["username"].isnull().all():
            st.info("No student quiz data yet. Flagged students and analytics will appear after quizzes are taken.")
        else:
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
                if 'topic' in user_rows.columns and not user_rows['topic'].isnull().all():
                    st.markdown("**By Topic:**")
                    st.dataframe(user_rows.groupby("topic")["correct"].mean().reset_index().rename(columns={"correct": "Score"}))
                if 'blooms_level' in user_rows.columns and not user_rows['blooms_level'].isnull().all():
                    st.markdown("**By Bloom's Level:**")
                    st.dataframe(user_rows.groupby("blooms_level")["correct"].mean().reset_index().rename(columns={"correct": "Score"}))
                st.markdown("**Raw Results:**")
                st.dataframe(user_rows, use_container_width=True)

            csv = flagged.to_csv(index=False)
            st.download_button("Download flagged report CSV", csv, "flagged_students.csv", "text/csv")
    except Exception as e:
        st.error(f"Admin dashboard error: {e}")

# ---------- STUDENT PERFORMANCE SUMMARY ----------
with st.expander("📊 Show My Performance Summary", expanded=False):
    try:
        df = pd.read_csv(log_path)
        user_df = df[df["username"] == username] if user_role != "admin" else df
        correct_total = user_df["correct"].sum()
        incorrect_total = len(user_df) - correct_total

        st.write(f"Total Questions Answered: {len(user_df)}")
        st.write(f"✅ Correct: {correct_total}")
        st.write(f"❌ Incorrect: {incorrect_total}")

        if not user_df.empty:
            fig, ax = plt.subplots()
            ax.bar(["Correct", "Incorrect"], [correct_total, incorrect_total])
            ax.set_ylabel("Number of Responses")
            ax.set_title("Student Performance")
            st.pyplot(fig)

    except Exception as e:
        st.warning("⚠️ No grading data available or error reading log.")
        st.text(str(e))
