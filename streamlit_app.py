import streamlit as st
import openai
from openai import OpenAI
import os
import PyPDF2

# Title and course selector
st.title("💬 PTA Tutor Chatbot")

# Course selector dropdown
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

# Truncate to prevent token overload
pdf_text = load_pdf_text(course)[:3000]  # Limit to ~3,000 characters

# Load API key
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# Session state for chat memory
if "messages" not in st.session_state:
    st.session_state.messages = []

# Show previous chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask a question about your course..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # System prompt using PDF content
    system_prompt = {
        "role": "system",
        "content": (
            "You are a helpful and focused tutor supporting students in a Physical Therapist Assistant (PTA) program. "
            "You should only answer using the following course material:\n\n"
            + pdf_text +
            "\n\nIf the question is outside this material, politely say you cannot answer."
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

        assistant_reply = response.choices[0].message.content
        with st.chat_message("assistant"):
            st.markdown(assistant_reply)

        st.session_state.messages.append({
            "role": "assistant",
            "content": assistant_reply
        })

    except openai.RateLimitError:
        st.error("⚠️ Rate limit reached. Wait a few minutes or check usage.")
    except Exception as e:
        st.error(f"❌ An error occurred: {str(e)}")



