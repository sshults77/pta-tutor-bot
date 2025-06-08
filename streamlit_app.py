import streamlit as st
import openai
from openai import OpenAI

# Title and description
st.title("💬 PTA Tutor Chatbot")
st.write(
    "This chatbot uses OpenAI's GPT-3.5 model to help PTA students review and study. "
    "Make sure your OpenAI API key is saved in Streamlit secrets for full access."
)

# Load API key from secrets
openai_api_key = st.secrets["openai"]["api_key"]
openai.api_key = openai_api_key
client = OpenAI(api_key=openai_api_key)

# Set up chat history if not already initialized
if "messages" not in st.session_state:
    st.session_state.messages = []

# Show prior messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Input from user
if prompt := st.chat_input("Ask me anything about PTA..."):
    # Store user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Define the system prompt
    system_prompt = {
        "role": "system",
        "content": (
            "You are a friendly, accurate, and supportive chatbot tutor for students "
            "in a Physical Therapist Assistant (PTA) program. Use the uploaded course materials "
            "when possible. Focus on helping students prepare for their coursework and licensing exam. "
            "Provide examples, quizzes, and explanations appropriate for PTA students. "
            "Do not give unrelated advice or answer outside of the PTA curriculum."
        )
    }

    # Get response from OpenAI
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

        # Show response and save to chat history
        assistant_reply = response.choices[0].message.content
        with st.chat_message("assistant"):
            st.markdown(assistant_reply)

        st.session_state.messages.append({
            "role": "assistant",
            "content": assistant_reply
        })

    except openai.RateLimitError:
        st.error("⚠️ OpenAI rate limit reached. Try again in a few minutes or check your API usage.")
    except Exception as e:
        st.error(f"❌ An unexpected error occurred: {str(e)}")


