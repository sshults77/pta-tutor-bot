import streamlit_authenticator as stauth

# List all your test passwords here, one per user
passwords = [
    'test1234',  # kbooth
    'test1234',  # kboothadmin
    'test1234',  # sshults
    'test1234',  # sshultsadmin
    'test1234',  # tallen
    'test1234',  # tallenadmin
]
hashes = stauth.Hasher(passwords).generate()
for i, h in enumerate(hashes):
    print(f"User {i+1}: {h}")
