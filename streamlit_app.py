import streamlit as st
import openai
from openai import OpenAI
import os
import json
import pdfplumber
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# --- Setup ---
st.set_page_config(page_title="PTA Tutor Chatbot", layout="wide")
st.title("💬 PTA Tutor Chatbot with Quiz & Performance Tracking")

# Select course
course = st.selectbox("Select your course:", ["PTA_1010"])

# Load PDF text from selected course folder
def load_pdf_text(course_folder):
    folder_path = f"course_materials/{course_folder}"
    full_text = ""
    if os.path.exists(folder_path):
        for filename in os.listdir(folder_path):
            if filename.endswith(".pdf"):
                pdf_path = os.path.join(folder_path, filename)
                with pdfplumber.open(pdf_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            full_text += page_text + "\n"
    return full_text

pdf_text = load_pdf_text(course)[:3000]

# Set OpenAI API key
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Chat Section ---
st.header("🗨️ Ask the PTA Tutor")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Handle new user prompt
if prompt := st.chat_input("Ask a question about your course..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    system_prompt = {
        "role": "system",
        "content": (
            "You are a helpful and focused tutor for Physical Therapist Assistant (PTA) students. "
            "Use only the following course content to answer:\n\n"
            + pdf_text +
            "\n\nIf the question is unrelated, say you can't answer."
        )
    }

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                system_prompt,
                *[
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ]
            ]
        )
        reply = response.choices[0].message.content
        with st.chat_message("assistant"):
            st.markdown(reply)

        st.session_state.messages.append({
            "role": "assistant",
            "content": reply
        })
    except openai.RateLimitError:
        st.error("⚠️ Rate limit reached. Try again later.")
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# --- Quiz Generator ---
st.markdown("---")
st.header("📝 Quiz Generator")

if st.button("Generate Quiz"):
    if not pdf_text:
        st.warning("No course material found.")
    else:
        quiz_prompt = (
            "You are a PTA tutor. Based on the following material, generate 3 multiple-choice questions. "
            "Each should have 4 options (A-D) and indicate the correct answer after each question. "
            "Use clear, concise clinical language appropriate for PTA students:\n\n"
            + pdf_text
        )
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": quiz_prompt}]
            )
            quiz_output = response.choices[0].message.content
            st.markdown("### ✅ Quiz Output")
            st.markdown(quiz_output)

            # Save quiz performance log for default user
            log_path = f"student_logs/default_user.json"
            os.makedirs(os.path.dirname(log_path), exist_ok=True)

            for line in quiz_output.split("\n"):
                if line.strip().startswith("Correct Answer:"):
                    answer = line.strip().split(":")[-1].strip()
                    question = quiz_output.split("Correct Answer:")[0].strip()
                    log_entry = {
                        "timestamp": datetime.now().isoformat(),
                        "question": question,
                        "correct_answer": answer,
                        "student_answer": "",  # Placeholder
                        "is_correct": None
                    }
                    if os.path.exists(log_path):
                        with open(log_path, "r") as f:
                            logs = json.load(f)
                    else:
                        logs = []

                    logs.append(log_entry)
                    with open(log_path, "w") as f:
                        json.dump(logs, f, indent=2)

        except Exception as e:
            st.error(f"❌ Failed to generate quiz: {str(e)}")

# --- Performance Tracker ---
st.markdown("---")
st.header("📊 Performance Summary")

log_path = "student_logs/default_user.json"
if os.path.exists(log_path):
    df = pd.read_json(log_path)

    if not df.empty:
        summary = df["is_correct"].value_counts().reindex([True, False], fill_value=0)
        fig, ax = plt.subplots()
        summary.plot(kind="bar", ax=ax, color=["green", "red"])
        ax.set_title("Correct vs Incorrect Answers")
        ax.set_ylabel("Number of Questions")
        ax.set_xticklabels(["Correct", "Incorrect"], rotation=0)
        st.pyplot(fig)

        st.markdown(f"**Total Questions:** {len(df)}  \n"
                    f"**Correct:** {summary[True]}  \n"
                    f"**Incorrect:** {summary[False]}")
    else:
        st.info("📭 No answered quiz data available.")
else:
    st.info("📭 No quiz history found yet.")
