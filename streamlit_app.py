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

# --- OpenAI setup (NO OpenAI object needed) ---
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key

log_path = Path("grading_log.csv")
if not log_path.exists():
    pd.DataFrame(columns=[
        "username", "question_id", "question_text", "user_answer",
        "correct_answer", "correct", "timestamp", "topic", "blooms_level"
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

Use ONLY this course content to answer questions:

{course_content}

If the question is unrelated to the material, respond: 'I'm sorry, I can only help with the course content provided.'"""
    }

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[system_prompt] + st.session_state.messages
        )
        reply = response['choices'][0]['message']['content']
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

    # Ask for topic tagging in prompt!
    quiz_prompt = (
        f"You are a Physical Therapist Assistant tutor. Based on the following course content, "
        f"{blooms_instruction}"
        "For each question:\n"
        "1) State the Topic and Bloom's Taxonomy level,\n"
        "2) Present the question in official NPTE exam style,\n"
        "3) Provide 4 answer options (A-D),\n"
        "4) List the correct answer after each question,\n"
        "5) Output the following JSON after each question for logging: "
        "{'topic': <topic>, 'blooms_level': <blooms_level>}\n"
        "Use only the provided material.\n\n"
        + course_content
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": quiz_prompt}]
        )
        quiz_text = response['choices'][0]['message']['content']
        st.markdown("### ✏️ Quiz Output")
        st.markdown(quiz_text)

        # ---- LOGGING (SIMULATED, replace this with real data in production) ----
        # Simulated log entries with topic and bloom's level for demo purposes:
        sample_log = [
            {
                "username": username,  
                "question_id": "Q001",
                "question_text": "What is the primary muscle responsible for knee extension?",
                "user_answer": "A",
                "correct_answer": "A",
                "correct": 1,
                "timestamp": datetime.now().isoformat(),
                "topic": "Knee Anatomy",
                "blooms_level": "1"
            },
            {
                "username": username,
                "question_id": "Q002",
                "question_text": "Which is a contraindication to ultrasound?",
                "user_answer": "C",
                "correct_answer": "A",
                "correct": 0,
                "timestamp": datetime.now().isoformat(),
                "topic": "Modalities",
                "blooms_level": "3"
            }
        ]

        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame(sample_log)], ignore_index=True)
        df.to_csv(log_path, index=False)

    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")

# --- Performance Summary, Weak Area Detection, Study Suggestions ---
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

        # --- Topic mastery breakdown
        st.write("### Topic Performance")
        weak_topics = []
        if not user_df.empty and "topic" in user_df.columns:
            topic_stats = user_df.groupby("topic")["correct"].agg(["sum", "count"])
            topic_stats["Accuracy (%)"] = 100 * topic_stats["sum"] / topic_stats["count"]
            st.dataframe(topic_stats[["sum", "count", "Accuracy (%)"]])

            for topic, row in topic_stats.iterrows():
                if row["Accuracy (%)"] < 70:
                    weak_topics.append(topic)

        # --- Bloom's level breakdown
        st.write("### Bloom's Level Performance")
        weak_blooms = []
        if not user_df.empty and "blooms_level" in user_df.columns:
            blooms_stats = user_df.groupby("blooms_level")["correct"].agg(["sum", "count"])
            blooms_stats["Accuracy (%)"] = 100 * blooms_stats["sum"] / blooms_stats["count"]
            st.dataframe(blooms_stats[["sum", "count", "Accuracy (%)"]])

            for level, row in blooms_stats.iterrows():
                if row["Accuracy (%)"] < 70:
                    weak_blooms.append(level)

        # --- Visual Summary ---
        fig, ax = plt.subplots()
        ax.bar(["Correct", "Incorrect"], [correct_total, incorrect_total])
        ax.set_ylabel("Number of Responses")
        ax.set_title("Student Performance")
        st.pyplot(fig)

        # --- Weak Areas and Suggestions ---
        st.write("### 📉 Areas for Improvement")
        if not weak_topics and not weak_blooms:
            st.success("No weak areas detected. Great job! 🎉")
        else:
            if weak_topics:
                st.error(f"Topics to Review: {', '.join(weak_topics)}")
            if weak_blooms:
                st.warning(f"Challenging Bloom's Levels: {', '.join(weak_blooms)}")

            st.write("#### 📚 Study Suggestions")
            if weak_topics:
                for topic in weak_topics:
                    st.write(f"- **{topic}:** Review your notes and course materials for this topic. Try re-answering practice questions or discuss with a study group.")
            if weak_blooms:
                for level in weak_blooms:
                    if str(level).startswith("1"):
                        st.write("- **Level 1 (Recall):** Focus on memorizing key facts and definitions. Use flashcards for repetitive review.")
                    elif str(level).startswith("2"):
                        st.write("- **Level 2 (Comprehension):** Practice explaining concepts in your own words or teaching someone else.")
                    elif str(level).startswith("3"):
                        st.write("- **Level 3 (Application):** Work through practice problems that require you to use concepts in scenarios.")
                    elif str(level).startswith("4"):
                        st.write("- **Level 4 (Analysis):** Break down case studies and identify relationships between concepts.")
                    elif str(level).startswith("5"):
                        st.write("- **Level 5 (Synthesis/Evaluation):** Practice critiquing and creating solutions to complex scenarios.")

    except Exception as e:
        st.warning("⚠️ No grading data available or error reading log.")
        st.text(str(e))
