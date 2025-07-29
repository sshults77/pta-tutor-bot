import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import os
import pdfplumber
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from pptx import Presentation
import openai
import json
import bcrypt  # <-- NEW

# --- Load users from YAML ---
try:
    with open('users.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    st.write("✅ Loaded users.yaml successfully!")
except Exception as e:
    st.error(f"❌ Error loading users.yaml: {e}")
    st.stop()

# --- HASH DEBUG: Check if kbooth password hash matches test1234 ---
if "credentials" in config and "usernames" in config["credentials"]:
    if "kbooth" in config["credentials"]["usernames"]:
        hash_from_yaml = config['credentials']['usernames']['kbooth']['password']
        # You can also check any other user this way
        password_plain = "test1234"
        try:
            # bcrypt hashes must be bytes!
            check_result = bcrypt.checkpw(password_plain.encode(), hash_from_yaml.encode())
        except Exception as e:
            check_result = f"ERROR: {e}"
        st.write("🔍 DEBUG: bcrypt.checkpw for kbooth / test1234 =", check_result)
    else:
        st.write("DEBUG: 'kbooth' user not found in YAML!")

# Debug: show the loaded usernames and roles
if "credentials" in config and "usernames" in config["credentials"]:
    st.write("DEBUG: Usernames found in YAML:", list(config["credentials"]["usernames"].keys()))
    for uname, details in config["credentials"]["usernames"].items():
        st.write(f"DEBUG: {uname} - role: {details.get('role')}, email: {details.get('email')}")
else:
    st.error("❌ Could not find 'credentials.usernames' in config!")
    st.stop()

try:
    authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )
except Exception as e:
    st.error(f"❌ Error initializing authenticator: {e}")
    st.stop()

# --- LOGIN ---
login_result = authenticator.login(location='main')
st.write("DEBUG: Raw login_result =", login_result)

if login_result is None:
    st.warning("DEBUG: login_result is None, stopping app")
    st.stop()

# Handle possible login result shapes
if isinstance(login_result, tuple):
    st.write("DEBUG: login_result as tuple:", login_result)
    if len(login_result) == 2:
        name, authentication_status = login_result
        username = getattr(authenticator, "username", None)
    elif len(login_result) == 3:
        name, authentication_status, username = login_result
    else:
        st.error(f"Unknown login return value structure: {login_result}")
        st.stop()
else:
    st.error(f"Unexpected login return type: {type(login_result)} Value: {login_result}")
    st.stop()

st.write("DEBUG: Login as:", username)
st.write("DEBUG: authentication_status:", authentication_status)

if authentication_status is False:
    st.error("Username/password is incorrect")
    st.stop()
elif authentication_status is None:
    st.warning("Please enter your username and password")
    st.stop()

# Continue with your main app here...
st.sidebar.write(f"Logged in as: **{name}** ({username})")
st.success("Login success! You now see the main app.")

# (rest of your code remains unchanged)

