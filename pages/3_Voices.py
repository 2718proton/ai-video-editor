import streamlit as st
import os

BASE_DIR = "assets"
VOICE_DIR = os.path.join(BASE_DIR, "voice")

st.set_page_config(page_title="Voice Manager", layout="wide")

st.title("Voice Manager")
st.write("View, preview, and delete all stored voice files.")

# Ensure folder exists
os.makedirs(VOICE_DIR, exist_ok=True)

# List files
files = os.listdir(VOICE_DIR)
files = [f for f in files if not f.startswith(".")]  # ignore hidden files

if not files:
    st.info("No voice files found.")
else:
    for f in files:
        file_path = os.path.join(VOICE_DIR, f)
        cols = st.columns([0.3, 0.5, 0.2])

        # Audio player preview
        try:
            cols[0].audio(file_path)
        except Exception:
            cols[0].warning("Cannot preview")

        # Info
        file_size_kb = os.path.getsize(file_path) // 1024
        cols[1].write(f"**Name:** {f}")
        cols[1].write(f"**Path:** `{file_path}`")
        cols[1].write(f"**Size:** {file_size_kb} KB")

        # Delete
        delete_key = f"delete_{f}"
        if cols[2].button("🗑 Delete", key=delete_key):
            os.remove(file_path)
            st.success(f"Deleted {f}")
            st.rerun()