import streamlit as st
import openai
from openai import OpenAI
import os
import PyPDF2

# Title and course selector
st.title("💬 PTA Tutor Chatbot")

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
                        full_text += page.extract_text() or ""
    return full_text

pdf_text = load_pdf_text(course)

# Load API key from secrets
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# Set up session history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User input
if prompt := st.chat_input("Ask a question about your course..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Define system prompt using the PDF content
    system_prompt = {
        "role": "system",
        "content": (
            "You are a supportive tutor helping PTA students prepare for coursework and licensure. "
            "Use only the following course materials to answer questions:\n\n"
            + pdf_text +
            "\n\nDo not answer outside of this content."
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
        st.error("⚠️ OpenAI rate limit reached. Try again in a few minutes.")
    except Exception as e:
        st.error(f"❌ An unexpected error occurred: {str(e)}")



