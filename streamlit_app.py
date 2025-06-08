import streamlit as st
import openai
from openai import OpenAI
import os
import PyPDF2

# Page title
st.title("💬 PTA Tutor Chatbot & Quiz Generator")

# Course selector
course = st.selectbox("Select your course:", ["PTA_1010"])

# Load PDF content
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

# Truncate long PDFs to stay under token limits
pdf_text = load_pdf_text(course)[:3000]

# OpenAI setup
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# --- QUIZ GENERATOR SECTION ---
st.markdown("## 📝 Quiz Generator")
if st.button("Generate Quiz"):
    if not pdf_text:
        st.warning("No PDF content found for this course.")
    else:
        try:
            quiz_prompt = (
                "You are a PTA tutor. Based on the following material, generate 3 multiple-choice questions. "
                "Each should have 4 options (A-D) and indicate the correct answer after each question. "
                "Use clear, concise clinical language appropriate for PTA students:\n\n"
                + pdf_text
            )

            response = client.cha
