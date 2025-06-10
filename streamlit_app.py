import streamlit as st
import openai
from openai import OpenAI
import os
import pdfplumber
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path

# Title
st.title("📚 PTA Tutor Chatbot with Quiz & Performance Tracker")

# --- Course Selection ---
course = st.selectbox("Select your course:", ["PTA_1010"])
course_folder = f"course_materials/{course}"

# --- Load PDF content ---
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

# --- OpenAI setup ---
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# --- Grading log setup ---
log_path = Path("grading_log.csv")
if not log_path.exists():
    pd.DataFrame(columns=[
        "question_id", "question_text", "user_answer",
        "correct_answer", "correct", "timestamp"
    ]).to_csv(log_path, index=False)

# --- Chatbot Section ---
st.header("💬 Chat with the Tutor")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display prior messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Handle input
if prompt := st.chat_input("Ask a question about your course..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    system_prompt = {
        "role": "system",
        "content": f"""You are a knowledgeable and focused PTA tutor.
Use ONLY this course content to answer questions:

{pdf_text}

If the question is unrelated to the material, respond: 'I'm sorry, I can only help wi
