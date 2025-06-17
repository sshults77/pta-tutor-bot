import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

with open('users.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

login_result = authenticator.login('Login')
st.write("login_result:", login_result)

if login_result is None:
    st.write("login_result is None, stopping.")
    st.stop()

if isinstance(login_result, tuple):
    st.write("login_result is tuple:", login_result)
    if len(login_result) == 2:
        name, authentication_status = login_result
        username = getattr(authenticator, "username", None)
        st.write("username:", username)
    elif len(login_result) == 3:
        name, authentication_status, username = login_result
    else:
        st.error("Unknown login return value structure.")
        st.write(login_result)
        st.stop()
else:
    st.error("Unexpected login return type.")
    st.write("Type:", type(login_result))
    st.write("Value:", login_result)
    st.stop()

st.write("authentication_status:", authentication_status)

if authentication_status is False:
    st.error("Username/password is incorrect")
    st.stop()
elif authentication_status is None:
    st.warning("Please enter your username and password")
    st.stop()

st.success("Login success! You now see the main app.")
st.sidebar.write(f"Logged in as: **{name}** ({username})")
st.write("Put your main app code here!")
