import streamlit as st
import os
from PIL import Image

BASE_DIR = "assets"
IMAGE_DIR = os.path.join(BASE_DIR, "images")

st.set_page_config(page_title="Image Manager", layout="wide")

st.title("Image Manager")
st.write("View, preview, and delete all stored images.")

# Ensure folder exists
os.makedirs(IMAGE_DIR, exist_ok=True)

# List files
files = os.listdir(IMAGE_DIR)
files = [f for f in files if not f.startswith(".")]  # ignore hidden files

if not files:
    st.info("No images found.")
else:
    for f in files:
        file_path = os.path.join(IMAGE_DIR, f)
        cols = st.columns([0.3, 0.5, 0.2])

        # Preview
        try:
            img = Image.open(file_path)
            cols[0].image(img, width=150)
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
