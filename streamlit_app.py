import streamlit as st
import openai
from openai import OpenAI
import os
import json
import PyPDF2
from datetime import datetime

# --- Setup ---
st.title("💬 PTA Tutor Chatbot & Quiz Logger")
course = st.selectbox("Select your course:", ["PTA_1010"])

# --- Load PDF content ---
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
                        text = page.extract_text()
                        if text:
                            full_text += text
    return full_text

pdf_text = load_pdf_text(course)[:3000]

# --- OpenAI setup ---
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# --- Chat Section ---
st.markdown("## 💬 Tutor Chat")
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

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
            messages=[system_prompt] + st.session_state.messages
        )
        reply = response.choices[0].message.content
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})

    except openai.RateLimitError:
        st.error("⚠️ Rate limit reached. Try again later.")
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# --- Quiz Generator + Logger ---
st.markdown("---")
st.markdown("## 📝 Quiz Me on This Course")

if st.button("Generate Quiz"):
    if not pdf_text:
        st.warning("No PDF content found.")
    else:
        quiz_prompt = (
            "Create 3 multiple-choice questions based on the following content. "
            "Each should have 4 options (A-D), clearly marked, and the correct answer indicated after each question.\n\n"
            + pdf_text
        )
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": quiz_prompt}]
            )
            quiz_output = response.choices[0].message.content
            st.session_state.current_quiz = quiz_output
        except Exception as e:
            st.error(f"Quiz generation failed: {e}")

# --- Show quiz and collect answers ---
if "current_quiz" in st.session_state:
    st.markdown("### Your Quiz")
    st.markdown(st.session_state.current_quiz)

    student_answers = st.text_area("Enter your answers (e.g., A, C, B):").strip().upper()
    if st.button("Submit Answers"):
        correct_count = 0
        results = []
        quiz_lines = st.session_state.current_quiz.split("\n")
        answer_index = 0
        for i, line in enumerate(quiz_lines):
            if "Answer:" in line:
                question_text = "\n".join(quiz_lines[i-5:i])
                correct = line.split("Answer:")[-1].strip().upper()
                student = student_answers.split(",")[answer_index].strip() if answer_index < len(student_answers.split(",")) else ""
                is_correct = student == correct
                results.append({
                    "timestamp": datetime.now().isoformat(),
                    "question": question_text,
                    "student_answer": student,
                    "correct_answer": correct,
                    "result": "✅" if is_correct else "❌"
                })
                answer_index += 1
                if is_correct:
                    correct_count += 1

        st.markdown(f"### 📊 Score: {correct_count} / {len(results)}")
        for r in results:
            st.markdown(f"**Q:** {r['question']}\n- Your answer: {r['student_answer']} ({r['result']})\n- Correct: {r['correct_answer']}")

        # --- Logging ---
        os.makedirs("student_logs", exist_ok=True)
        log_path = "student_logs/default_user.json"
        try:
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    data = json.load(f)
            else:
                data = []
            data.extend(results)
            with open(log_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            st.error(f"Failed to save log: {e}")

