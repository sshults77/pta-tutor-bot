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
import re
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


# ---------- NEW: QUIZ PARSER ----------------
def extract_question_metadata(quiz_output):
    """
    Extracts question blocks, answers, and their associated JSON metadata
    from GPT output.
    Returns a list of dicts: [{
        "question_text": ...,
        "options": ...,
        "correct_answer": ...,
        "topic": ...,
        "blooms_level": ...
    }, ...]
    """
    question_blocks = re.split(r'\n\s*Question \d+:', quiz_output, flags=re.IGNORECASE)
    results = []

    for block in question_blocks:
        block = block.strip()
        if not block:
            continue

        json_match = re.search(r'\{.*\}', block)
        topic = blooms_level = None
        if json_match:
            try:
                meta = json.loads(json_match.group())
                topic = meta.get("topic")
                blooms_level = meta.get("blooms_level")
            except Exception:
                pass

        correct = None
        corr_match = re.search(r'Correct Answer: ([A-D])', block)
        if corr_match:
            correct = corr_match.group(1)

        qtext_match = re.match(r'([^\n]+)\n', block)
        question_text = qtext_match.group(1).strip() if qtext_match else "Unknown"

        options = []
        for opt in "ABCD":
            m = re.search(rf"{opt}\.\s*(.+)", block)
            if m:
                options.append(f"{opt}. {m.group(1).strip()}")

        results.append({
            "question_text": question_text,
            "options": options,
            "correct_answer": correct,
            "topic": topic,
            "blooms_level": blooms_level
        })

    return results

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

    # --- INSTRUCT GPT TO INCLUDE JSON METADATA! ---
    if bloom_option.startswith("Mixed"):
        blooms_instruction = (
            "Generate 5 NPTE-style multiple-choice questions: "
            "one each at Bloom's Level 1 (Recall/Knowledge), "
            "Level 2 (Comprehension), Level 3 (Application), "
            "Level 4 (Analysis), and Level 5 (Synthesis/Evaluation). "
            "After each question, include a JSON object on its own line in the format: "
            '{"topic": "...", "blooms_level": "..."}'
        )
    else:
        level = bloom_option[0]
        level_name = blooms_level_map.get(level, "")
        blooms_instruction = (
            f"Generate 5 NPTE-style multiple-choice questions at Bloom's Level {level} ({level_name}). "
            "After each question, include a JSON object on its own line in the format: "
            '{"topic": "...", "blooms_level": "..."}'
        )

    quiz_prompt = (
        f"You are a Physical Therapist Assistant tutor. Based on the following course content, "
        f"{blooms_instruction} "
        "For each question: "
        "1) State the Bloom's Taxonomy level, "
        "2) Present the question in official NPTE exam style, "
        "3) Provide 4 answer options (A-D), "
        "4) List the correct answer after each question. "
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

        # --- Parse questions and log metadata ---
        parsed_questions = extract_question_metadata(quiz_text)
        log_entries = []
        for idx, q in enumerate(parsed_questions):
            log_entries.append({
                "username": username,
                "question_id": f"Q{str(idx+1).zfill(3)}",
                "question_text": q["question_text"],
                "user_answer": "",  # You can update this if you collect answers!
                "correct_answer": q["correct_answer"],
                "correct": None,
                "timestamp": datetime.now().isoformat(),
                "topic": q["topic"] or "",
                "blooms_level": q["blooms_level"] or ""
            })
        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame(log_entries)], ignore_index=True)
        df.to_csv(log_path, index=False)

    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")

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

        fig, ax = plt.subplots()
        ax.bar(["Correct", "Incorrect"], [correct_total, incorrect_total])
        ax.set_ylabel("Number of Responses")
        ax.set_title("Student Performance")
        st.pyplot(fig)

    except Exception as e:
        st.warning("⚠️ No grading data available or error reading log.")
        st.text(str(e))
