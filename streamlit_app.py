import streamlit as st
import openai
from openai import OpenAI
import os
import pdfplumber
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# Title
st.title("📚 PTA Tutor Chatbot with Quiz & Performance Tracker")

# Course selection
course = st.selectbox("Select your course:", ["PTA_1010"])
course_folder = f"course_materials/{course}"

# Load PDF text
def load_pdf_text(folder):
    text = ""
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            if filename.endswith(".pdf"):
                file_path = os.path.join(folder, filename)
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        text += page.extract_text() or ""
    return text

pdf_text = load_pdf_text(course_folder)[:3000]  # Token limit control

# OpenAI setup
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# Load grading log
log_path = "/mnt/data/grading_log.csv"
if not os.path.exists(log_path):
    pd.DataFrame(columns=[
        "question_id", "question_text", "user_answer",
        "correct_answer", "correct", "timestamp"
    ]).to_csv(log_path, index=False)

# --- Chat Section ---
st.header("💬 Chat with the Tutor")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display prior chat
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
            "You are a knowledgeable and focused PTA tutor. "
            "Use ONLY this course content to answer questions:\n\n" + pdf_text
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
        st.error(f"❌ Error: {str(e)}")

# --- Quiz Generator ---
st.header("📝 Quiz Generator")

if st.button("Generate Quiz"):
    quiz_prompt = (
        "You are a PTA tutor. Based on the following course material, create 3 multiple-choice questions. "
        "Each should have 4 options (A–D) and include the correct answer after each question:\n\n" + pdf_text
    )
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": quiz_prompt}]
        )
        quiz_text = response.choices[0].message.content
        st.markdown("### ✏️ Quiz Output")
        st.markdown(quiz_text)

        # Simulated grading (you can adapt to your own logic)
        sample_log = [
            {
                "question_id": "Q001",
                "question_text": "What is the primary muscle responsible for knee extension?",
                "user_answer": "A",
                "correct_answer": "A",
                "correct": 1,
                "timestamp": datetime.now().isoformat()
            },
            {
                "question_id": "Q002",
                "question_text": "Which of the following is a contraindication to ultrasound?",
                "user_answer": "C",
                "correct_answer": "A",
                "correct": 0,
                "timestamp": datetime.now().isoformat()
            }
        ]
        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame(sample_log)], ignore_index=True)
        df.to_csv(log_path, index=False)

    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")

# --- Performance Summary ---
st.header("📊 Performance Summary")

try:
    df = pd.read_csv(log_path)
    correct_total = df["correct"].sum()
    incorrect_total = len(df) - correct_total

    st.write(f"Total Questions Answered: {len(df)}")
    st.write(f"Correct: {correct_total}, Incorrect: {incorrect_total}")

    # Bar Chart
    fig, ax = plt.subplots()
    ax.bar(["Correct", "Incorrect"], [correct_total, incorrect_total])
    ax.set_ylabel("Number of Answers")
    ax.set_title("Student Quiz Performance")
    st.pyplot(fig)

except Exception as e:
    st.warning("⚠️ No grading data available or error reading log.")
    st.text(str(e))

