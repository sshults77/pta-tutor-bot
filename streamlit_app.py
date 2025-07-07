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
import csv

# --- Configuration constants ---
COURSE_MATERIALS_ROOT = "course_materials"
INSTRUCTOR_EMAILS_FILE = "instructor_emails.csv"
LOG_PATH = Path("grading_log.csv")

# --- Helper: Load users from YAML ---
def load_auth_config():
    with open('users.yaml') as file:
        return yaml.load(file, Loader=SafeLoader)

# --- Helper: Instructor email storage and retrieval ---
def load_instructor_emails():
    emails = {}
    if os.path.exists(INSTRUCTOR_EMAILS_FILE):
        with open(INSTRUCTOR_EMAILS_FILE, "r", newline="") as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if len(row) == 2:
                    emails[row[0]] = row[1]
    return emails

def save_instructor_email(username, email):
    emails = load_instructor_emails()
    emails[username] = email.strip()
    with open(INSTRUCTOR_EMAILS_FILE, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        for user, mail in emails.items():
            writer.writerow([user, mail])

def get_instructor_email(username):
    emails = load_instructor_emails()
    return emails.get(username, "")

# --- Helper: Course discovery ---
def discover_courses(root_dir):
    """Return sorted list of all course subfolders."""
    if not os.path.exists(root_dir):
        return []
    return sorted([d for d in os.listdir(root_dir) if os.path.isdir(os.path.join(root_dir, d))])

# --- Helper: Load text from PDFs in folder ---
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

# --- Helper: Load text from TXT in folder ---
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

# --- Helper: Extract PPTX notes ---
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

# --- Auth and login ---
config = load_auth_config()
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
user_role = config['credentials']['usernames'][username]['role']
st.sidebar.write(f"Logged in as: **{name}** ({username})")
st.success("Login success! You now see the main app.")

# --- OpenAI key setup ---
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key

# --- Dynamic Course Selection ---
courses = discover_courses(COURSE_MATERIALS_ROOT)
if not courses:
    courses = ["PTA_1010"]  # fallback if root is empty
course = st.selectbox("Select your course:", courses)
course_folder = os.path.join(COURSE_MATERIALS_ROOT, course)

# --- Load all course content
pdf_text = load_pdf_text(course_folder)[:3000]
txt_text = load_txt_content(course_folder)[:3000]
st.sidebar.header("Optional: Upload PowerPoint for Chatbot Content")
uploaded_pptx = st.sidebar.file_uploader("Upload a PowerPoint (.pptx)", type="pptx")
pptx_text = ""
if uploaded_pptx:
    pptx_text = extract_notes_from_uploaded_pptx(uploaded_pptx)
    st.sidebar.success("PowerPoint notes extracted. Chatbot will use these as course content.")

# --- Grading log setup with topic and Bloom's fields
if not LOG_PATH.exists():
    pd.DataFrame(columns=[
        "username", "question_id", "question_text", "user_answer",
        "correct_answer", "correct", "topic", "blooms_level", "timestamp"
    ]).to_csv(LOG_PATH, index=False)

# --- Chatbot Section ---
st.title("📚 PTA Tutor Chatbot with Quiz & Performance Tracker")
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
    # Pick content source
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

# --- Quiz Generator Section ---
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
        # --- Simulated grading (update for real answer parsing)
        sample_log = [
            {
                "username": username,
                "question_id": "Q001",
                "question_text": "What is the primary muscle responsible for knee extension?",
                "user_answer": "A",
                "correct_answer": "A",
                "correct": 1,
                "topic": "Knee Anatomy",
                "blooms_level": "1",
                "timestamp": datetime.now().isoformat()
            },
            {
                "username": username,
                "question_id": "Q002",
                "question_text": "Which is a contraindication to ultrasound?",
                "user_answer": "C",
                "correct_answer": "A",
                "correct": 0,
                "topic": "Modalities",
                "blooms_level": "2",
                "timestamp": datetime.now().isoformat()
            }
        ]
        df = pd.read_csv(LOG_PATH)
        df = pd.concat([df, pd.DataFrame(sample_log)], ignore_index=True)
        df.to_csv(LOG_PATH, index=False)
    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")

# --- Instructor Dashboard (admin only) ---
if user_role == "admin":
    st.header("📊 Instructor Dashboard: Flagged/Struggling Students")
    # Notification email setup UI
    st.markdown("#### 📧 Set Your Notification Email")
    current_email = get_instructor_email(username)
    email_input = st.text_input("Your notification email:", value=current_email)
    if st.button("Save Notification Email"):
        save_instructor_email(username, email_input)
        st.success(f"Notification email updated to: {email_input}")
    min_score_frac = st.slider("Minimum score for NOT being flagged (as a fraction)", 0.0, 1.0, 0.7, 0.05)
    min_attempts = st.number_input("Minimum number of quiz attempts to be considered", 1, 20, 3, 1)
    try:
        df = pd.read_csv(LOG_PATH)
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

# --- Student Performance Summary ---
with st.expander("📊 Show My Performance Summary", expanded=False):
    try:
        df = pd.read_csv(LOG_PATH)
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
