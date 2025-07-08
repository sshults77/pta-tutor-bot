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

# Get user role for instructor dashboard
user_role = config['credentials']['usernames'][username]['role']

st.sidebar.write(f"Logged in as: **{name}** ({username})")
st.success("Login success! You now see the main app.")

# --- Main App ---
st.title("📚 PTA Tutor Chatbot with Quiz & Performance Tracker")

# --- Dynamic course discovery
COURSE_MATERIALS_ROOT = "course_materials"
courses = [d for d in os.listdir(COURSE_MATERIALS_ROOT)
           if os.path.isdir(os.path.join(COURSE_MATERIALS_ROOT, d))]
if not courses:
    courses = ["PTA_1010"]  # fallback

course = st.selectbox("Select your course:", sorted(courses))
course_folder = os.path.join(COURSE_MATERIALS_ROOT, course)

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

# --- OpenAI setup ---
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key

log_path = Path("grading_log.csv")
if not log_path.exists():
    pd.DataFrame(columns=[
        "username", "quiz_id", "question_id", "question_text", "user_answer",
        "correct_answer", "correct", "topic", "blooms_level", "question_type",
        "time_spent", "cohort", "timestamp"
    ]).to_csv(log_path, index=False)

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

# --- Quiz Generator with Blooms Levels 1–5 ---
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

if st.button("Generate Quiz"):
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
        "Use only the provided material.\n\n"
        + course_content
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": quiz_prompt}]
        )
        quiz_text = response.choices[0].message.content
        st.markdown("### ✏️ Quiz Output")
        st.markdown(quiz_text)

        # Simulated grading - replace with actual user answer collection as needed!
        sample_log = [
            {
                "username": username,
                "quiz_id": "quiz1",
                "question_id": "Q001",
                "question_text": "What is the primary muscle responsible for knee extension?",
                "user_answer": "A",
                "correct_answer": "A",
                "correct": 1,
                "topic": "Knee Anatomy",
                "blooms_level": "1",
                "question_type": "multiple_choice",
                "time_spent": 45,
                "cohort": "2025A",
                "timestamp": datetime.now().isoformat()
            },
            {
                "username": username,
                "quiz_id": "quiz1",
                "question_id": "Q002",
                "question_text": "Which is a contraindication to ultrasound?",
                "user_answer": "C",
                "correct_answer": "A",
                "correct": 0,
                "topic": "Modalities",
                "blooms_level": "2",
                "question_type": "multiple_choice",
                "time_spent": 40,
                "cohort": "2025A",
                "timestamp": datetime.now().isoformat()
            }
        ]

        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame(sample_log)], ignore_index=True)
        df.to_csv(log_path, index=False)

    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")

# --- Instructor Drill-Down Dashboard (NEW SECTION) ---
if user_role == "admin":
    st.header("📊 Instructor Drill-Down Dashboard")

    # --- Load Grading Log Data ---
    try:
        df = pd.read_csv(log_path, parse_dates=["timestamp"])
    except Exception as e:
        st.error(f"Could not read grading log: {e}")
        st.stop()

    # --- Sidebar Filters ---
    st.sidebar.subheader("Drill-Down Filters")
    students = ["All"] + sorted(df["username"].dropna().unique().tolist())
    student_filter = st.sidebar.selectbox("Student", students)
    
    blooms_levels = ["All"] + sorted(df["blooms_level"].dropna().astype(str).unique().tolist())
    blooms_filter = st.sidebar.selectbox("Bloom's Level", blooms_levels)

    # Date range filter
    if "timestamp" in df.columns:
        date_min, date_max = df["timestamp"].min(), df["timestamp"].max()
        date_range = st.sidebar.date_input("Date Range", [date_min, date_max])
    else:
        date_range = []

    quiz_ids = ["All"] + sorted(df["quiz_id"].dropna().unique().astype(str).tolist())
    quiz_filter = st.sidebar.selectbox("Quiz", quiz_ids)

    question_types = ["All"] + sorted(df.get("question_type", pd.Series([""])).dropna().unique().tolist())
    question_type_filter = st.sidebar.selectbox("Question Type", question_types)

    cohorts = ["All"] + sorted(df.get("cohort", pd.Series([""])).dropna().unique().tolist())
    cohort_filter = st.sidebar.selectbox("Cohort", cohorts)

    topics = ["All"] + sorted(df["topic"].dropna().unique().tolist())
    topic_filter = st.sidebar.selectbox("Topic", topics)

    # --- Apply Filters ---
    filtered = df.copy()
    if student_filter != "All":
        filtered = filtered[filtered["username"] == student_filter]
    if blooms_filter != "All":
        filtered = filtered[filtered["blooms_level"].astype(str) == blooms_filter]
    if quiz_filter != "All":
        filtered = filtered[filtered["quiz_id"].astype(str) == quiz_filter]
    if question_type_filter != "All" and "question_type" in filtered:
        filtered = filtered[filtered["question_type"] == question_type_filter]
    if cohort_filter != "All" and "cohort" in filtered:
        filtered = filtered[filtered["cohort"] == cohort_filter]
    if topic_filter != "All":
        filtered = filtered[filtered["topic"] == topic_filter]
    if "timestamp" in filtered.columns and len(date_range) == 2:
        filtered = filtered[
            (filtered["timestamp"] >= pd.to_datetime(date_range[0]))
            & (filtered["timestamp"] <= pd.to_datetime(date_range[1]))
        ]

    st.markdown("### 📈 Filtered Performance Data")
    st.dataframe(filtered, use_container_width=True)

    # --- Drill-Down Charts ---
    st.markdown("#### 🌱 Bloom’s Taxonomy Breakdown")
    if not filtered.empty:
        st.bar_chart(filtered.groupby("blooms_level")["correct"].mean())
    
    st.markdown("#### 📝 Quiz-by-Quiz Performance")
    if "quiz_id" in filtered:
        quiz_summary = filtered.groupby("quiz_id")["correct"].mean()
        st.line_chart(quiz_summary)

    if "time_spent" in filtered:
        st.markdown("#### ⏰ Time Spent vs. Score")
        st.scatter_chart(filtered[["time_spent", "correct"]])

    if "question_type" in filtered:
        st.markdown("#### ❓ Question Type Breakdown")
        st.bar_chart(filtered.groupby("question_type")["correct"].mean())

    if "cohort" in filtered:
        st.markdown("#### 🧑‍🎓 Cohort Comparison")
        st.bar_chart(filtered.groupby("cohort")["correct"].mean())

    st.markdown("#### 📚 Topic Sequence (First vs. Most Recent Attempt)")
    topic_first_last = (
        filtered.sort_values("timestamp")
        .groupby(["username", "topic"])
        .agg(first_score=("correct", "first"), last_score=("correct", "last"))
        .reset_index()
    )
    if not topic_first_last.empty:
        st.dataframe(topic_first_last, use_container_width=True)

    # --- Download Filtered Results ---
    csv = filtered.to_csv(index=False)
    st.download_button("Download filtered data CSV", csv, "filtered_results.csv", "text/csv")

# --- Student Performance Summary ---
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
