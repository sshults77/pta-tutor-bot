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
import time

# --- Auth ---
with open('users.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

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

st.sidebar.write(f"Logged in as: **{name}** ({username})")
st.success("Login success! You now see the main app.")

# --- Main App ---
st.title("📚 PTA Tutor Chatbot with Quiz & Performance Tracker")

course = st.selectbox("Select your course:", ["PTA_1010"])
course_folder = f"course_materials/{course}"

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

pdf_text = load_pdf_text(course_folder)[:3000]
txt_text = load_txt_content(course_folder)[:3000]

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
        "correct_answer", "correct", "timestamp",
        "topic", "blooms_level", "question_type", "time_spent"
    ]).to_csv(log_path, index=False)

# --- Quiz Generator with Bloom's Levels and Topic Tracking ---
st.header("📝 Quiz Generator & Adaptive Logger")

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

# Persistent quiz state (per session)
if "quiz_questions" not in st.session_state:
    st.session_state.quiz_questions = []
if "quiz_started" not in st.session_state:
    st.session_state.quiz_started = False
if "quiz_start_time" not in st.session_state:
    st.session_state.quiz_start_time = None

def generate_quiz():
    # Determine content source
    if pptx_text:
        course_content = pptx_text
        content_source = "PowerPoint notes"
    elif txt_text:
        course_content = txt_text
        content_source = "Text file"
    else:
        course_content = pdf_text
        content_source = "PDF"
    st.info(f"Quiz is using: {content_source}")

    blooms_level_map = {
        "1": "Recall/Knowledge",
        "2": "Comprehension",
        "3": "Application",
        "4": "Analysis",
        "5": "Synthesis/Evaluation"
    }

    if bloom_option.startswith("Mixed"):
        blooms_instruction = (
            "Generate 5 NPTE-style multiple-choice questions. "
            "For each, output JSON with keys: "
            "'question_id', 'question_text', 'options', 'correct_answer', 'blooms_level', 'topic'. "
            "Use Bloom's Level 1 (Recall), Level 2 (Comprehension), Level 3 (Application), Level 4 (Analysis), and Level 5 (Synthesis/Evaluation), one question for each. "
            "After the JSON, output a readable version for the student to answer."
        )
    else:
        level = bloom_option[0]
        level_name = blooms_level_map.get(level, "")
        blooms_instruction = (
            f"Generate 5 NPTE-style multiple-choice questions at Bloom's Level {level} ({level_name}). "
            "For each, output JSON with keys: "
            "'question_id', 'question_text', 'options', 'correct_answer', 'blooms_level', 'topic'. "
            "After the JSON, output a readable version for the student to answer."
        )

    quiz_prompt = (
        f"You are a Physical Therapist Assistant tutor. Based on the following course content, "
        f"{blooms_instruction}\n\n"
        f"Only use the provided course content. Here is the content:\n\n{course_content}"
    )

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": quiz_prompt}]
    )
    output = response['choices'][0]['message']['content']

    # Parse JSON blocks
    json_blocks = re.findall(r'```json(.*?)```', output, re.DOTALL)
    if not json_blocks:  # fallback: try curly braces
        json_blocks = re.findall(r'\{.*?\}', output, re.DOTALL)

    questions_data = []
    for block in json_blocks:
        try:
            q = json.loads(block)
            questions_data.append(q)
        except Exception:
            continue

    return questions_data

# --- Quiz UI ---

if st.button("Generate Quiz"):
    st.session_state.quiz_questions = generate_quiz()
    st.session_state.quiz_started = True
    st.session_state.quiz_start_time = time.time()
    st.session_state.quiz_answers = {}  # Reset answers

if st.session_state.quiz_started and st.session_state.quiz_questions:
    st.subheader("Answer the Quiz:")
    quiz_end = False
    for i, q in enumerate(st.session_state.quiz_questions):
        st.write(f"**Q{i+1}: {q['question_text']}**")
        answer = st.radio(
            f"Choose an answer for Q{i+1}", q['options'],
            key=f"quiz_answer_{i}"
        )
        st.session_state.quiz_answers[q['question_id']] = answer

    if st.button("Submit Answers"):
        quiz_end = True
        time_spent = time.time() - st.session_state.quiz_start_time
        time_per_q = time_spent / len(st.session_state.quiz_questions)

        # Log, grade, and provide feedback
        log_entries = []
        correct_count = 0
        for idx, q in enumerate(st.session_state.quiz_questions):
            user_answer = st.session_state.quiz_answers.get(q['question_id'], "")
            is_correct = 1 if user_answer.startswith(q['correct_answer']) else 0
            correct_count += is_correct
            st.markdown(
                f"**Q{idx+1} Feedback:** "
                f"{'✅ Correct!' if is_correct else f'❌ Incorrect. Correct answer: {q['correct_answer']}'}"
            )
            log_entries.append({
                "username": username,
                "question_id": q.get('question_id', f"Q{idx+1}"),
                "question_text": q.get('question_text', ''),
                "user_answer": user_answer,
                "correct_answer": q.get('correct_answer', ''),
                "correct": is_correct,
                "timestamp": datetime.now().isoformat(),
                "topic": q.get('topic', ''),
                "blooms_level": q.get('blooms_level', ''),
                "question_type": "multiple_choice",
                "time_spent": time_per_q
            })
        st.write(f"Your Score: {correct_count} / {len(st.session_state.quiz_questions)}")

        # Log to CSV
        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame(log_entries)], ignore_index=True)
        df.to_csv(log_path, index=False)

        # Reset for next quiz
        st.session_state.quiz_started = False

# --- Performance Summary ---
with st.expander("📊 Show Performance Summary", expanded=False):
    try:
        df = pd.read_csv(log_path)
        user_role = config['credentials']['usernames'][username]['role']
        if user_role == "admin":
            user_df = df
        else:
            user_df = df[df["username"] == username]
        correct_total = user_df["correct"].sum()
        incorrect_total = len(user_df) - correct_total

        st.write(f"Total Questions Answered: {len(user_df)}")
        st.write(f"✅ Correct: {correct_total}")
        st.write(f"❌ Incorrect: {incorrect_total}")

        # Topic mastery breakdown
        st.write("### Topic Performance")
        if not user_df.empty and "topic" in user_df.columns:
            topic_stats = user_df.groupby("topic")["correct"].agg(["sum", "count"])
            topic_stats["Accuracy (%)"] = 100 * topic_stats["sum"] / topic_stats["count"]
            st.dataframe(topic_stats[["sum", "count", "Accuracy (%)"]])

        # Bloom's level breakdown
        st.write("### Bloom's Level Performance")
        if not user_df.empty and "blooms_level" in user_df.columns:
            blooms_stats = user_df.groupby("blooms_level")["correct"].agg(["sum", "count"])
            blooms_stats["Accuracy (%)"] = 100 * blooms_stats["sum"] / blooms_stats["count"]
            st.dataframe(blooms_stats[["sum", "count", "Accuracy (%)"]])

        fig, ax = plt.subplots()
        ax.bar(["Correct", "Incorrect"], [correct_total, incorrect_total])
        ax.set_ylabel("Number of Responses")
        ax.set_title("Student Performance")
        st.pyplot(fig)

    except Exception as e:
        st.warning("⚠️ No grading data available or error reading log.")
        st.text(str(e))
