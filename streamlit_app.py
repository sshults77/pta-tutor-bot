import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

# ---- LOGIN BLOCK (Only for debug!) ----
with open('users.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

login_result = authenticator.login()

if login_result is None:
    st.stop()

if isinstance(login_result, tuple):
    if len(login_result) == 2:
        name, authentication_status = login_result
        username = getattr(authenticator, "username", None)
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

if authentication_status:
    authenticator.logout("Logout", "sidebar")
    st.sidebar.write(f"Logged in as: **{name}** ({username})")
    st.success("Login success! You now see the main app.")
    st.write("Put your main app code here!")
else:
    st.error("Username/password is incorrect")
    st.stop()
