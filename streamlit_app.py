import streamlit as st
import openai
from openai import OpenAI
import os
import pdfplumber
import json
from datetime import datetime

# Page title
st.title("💬 PTA Tutor Chatbot & Quiz Tracker")

# Course selector
course = st.selectbox("Select your course:", ["PTA_1010"])

# --- Load PDF content using pdfplumber ---
def load_pdf_text(course_folder):
    folder_path = f"course_materials/{course_folder}"
    full_text = ""
    if os.path.exists(folder_path):
        st.markdown("### 📄 Loaded PDF Files")
        for filename in os.listdir(folder_path):
            if filename.endswith(".pdf"):
                pdf_path = os.path.join(folder_path, filename)
                try:
                    with pdfplumber.open(pdf_path) as pdf:
                        text = ""
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text
                    char_count = len(text)
                    st.markdown(f"- ✅ **{filename}** ({char_count} characters extracted)")
                    full_text += text
                except Exception as e:
                    st.markdown(f"- ❌ **{filename}** could not be read: {e}")
    else:
        st.warning("No PDF folder found for this course.")
    return full_text

pdf_text = load_pdf_text(course)[:3000]  # Truncate to stay under token limits

# OpenAI setup
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# Default user (until login system)
user_id = "default_user"
log_file = f"student_logs/{user_id}.json"

# Ensure log file exists
if not os.path.exists("student_logs"):
    os.makedirs("student_logs")
if not os.path.exists(log_file):
    with open(log_file, "w") as f:
        json.dump([], f)

# --- Chat Section ---
st.markdown("## 💬 Tutor Chat")
if "messages" not in st.session_state:
    st.session_state.messages = []

# Show chat history
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
            "Answer questions using only this course content:\n\n"
            + pdf_text +
            "\n\nIf the question is unrelated, say you can't answer."
        )
    }

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                system_prompt,
                *[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
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

# --- Quiz Generator Section ---
st.markdown("---")
st.markdown("## 📝 Quiz Generator")

if st.button("Generate Quiz"):
    try:
        quiz_prompt = (
            "You are a PTA tutor. Based on the following material, generate 3 multiple-choice questions. "
            "Each should have 4 options (A-D) and indicate the correct answer after each question. "
            "Use clear, concise clinical language appropriate for PTA students:\n\n"
            + pdf_text
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": quiz_prompt}]
        )

        quiz_output = response.choices[0].message.content
        st.markdown("### ✅ Quiz Output")
        st.markdown(quiz_output)

        # Log quiz interaction
        log_entry = {
            "Date": str(datetime.now()),
            "Course": course,
            "Type": "quiz_generated",
            "Content": quiz_output
        }
        with open(log_file, "r+") as f:
            data = json.load(f)
            data.append(log_entry)
            f.seek(0)
            json.dump(data, f, indent=2)

    except Exception as e:
        st.error(f"❌ Failed to generate quiz: {str(e)}")


