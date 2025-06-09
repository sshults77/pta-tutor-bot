import streamlit as st
import openai
from openai import OpenAI
import os
import PyPDF2
import pandas as pd
import matplotlib.pyplot as plt
import json
from datetime import datetime

# Page title
st.title("💬 PTA Tutor Chatbot & Quiz Tracker")

# Select course
course = st.selectbox("Select your course:", ["PTA_1010"])

# Load PDFs
def load_pdf_text(course_folder):
    folder_path = f"course_materials/{course_folder}"
    full_text = ""
    if os.path.exists(folder_path):
        for filename in os.listdir(folder_path):
            if filename.endswith(".pdf"):
                pdf_path = os.path.join(folder_path, filename)
                with open(pdf_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            full_text += page_text
    return full_text

pdf_text = load_pdf_text(course)[:3000]

# OpenAI setup
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# Session state for messages
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
st.markdown("## 💬 Chat")
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask a question about your course..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    system_prompt = {
        "role": "system",
        "content": (
            "You are a helpful and focused tutor for Physical Therapist Assistant (PTA) students. "
            "Use only this course content to answer questions:\n\n"
            + pdf_text +
            "\n\nIf the question is unrelated, say you can't answer it."
        )
    }

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[system_prompt] + st.session_state.messages
        )
        reply = response.choices[0].message.content
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
    except Exception as e:
        st.error(f"❌ Error: {e}")

# --- QUIZ GENERATOR ---
st.markdown("---")
st.subheader("📝 Generate Quiz")

if st.button("Generate Quiz"):
    try:
        quiz_prompt = (
            "You are a PTA tutor. Based on the following material, generate 3 multiple-choice questions. "
            "Each should have 4 options (A-D) and indicate the correct answer after each question. "
            "Use clear, concise clinical language for PTA students:\n\n" + pdf_text
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": quiz_prompt}]
        )

        quiz = response.choices[0].message.content
        st.markdown("### ✅ Quiz")
        st.markdown(quiz)

        # Simulated grading (for now, we'll count all as correct to demo)
        correct = quiz.count("**Answer:")
        incorrect = 3 - correct

        log_path = "student_logs/default_user.json"
        os.makedirs("student_logs", exist_ok=True)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "course": course,
            "quiz_text": quiz,
            "correct": correct,
            "incorrect": incorrect
        }

        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                data = json.load(f)
        else:
            data = []

        data.append(log_entry)

        with open(log_path, "w") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        st.error(f"❌ Could not generate quiz: {e}")

# --- PERFORMANCE BAR CHART ---
st.markdown("---")
st.subheader("📊 Performance Summary")

log_path = "student_logs/default_user.json"
if os.path.exists(log_path):
    with open(log_path, "r") as f:
        log_data = json.load(f)

    df = pd.DataFrame(log_data)
    correct_total = df["correct"].sum()
    incorrect_total = df["incorrect"].sum()

    chart_data = pd.Series(
        {"Correct": correct_total, "Incorrect": incorrect_total}
    )

    fig, ax = plt.subplots()
    chart_data.plot(kind="bar", color=["green", "red"], ax=ax)
    ax.set_ylabel("Number of Questions")
    ax.set_title("Correct vs. Incorrect")
    st.pyplot(fig)

    st.markdown(f"**Total Questions Answered:** {correct_total + incorrect_total}  \n"
                f"**Correct:** {correct_total}  \n"
                f"**Incorrect:** {incorrect_total}")
else:
    st.info("No quiz attempts logged yet.")
