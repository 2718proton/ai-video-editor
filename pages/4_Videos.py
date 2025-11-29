import streamlit as st
import os

BASE_DIR = "video"

st.set_page_config(page_title="Video Manager", layout="wide")

st.title("Video Manager")
st.write("View, preview, and delete all generated videos.")

# Ensure folder exists
os.makedirs(BASE_DIR, exist_ok=True)

# List files
files = os.listdir(BASE_DIR)
files = [f for f in files if not f.startswith(".")]  # ignore hidden files
# Sort by modification time (newest first)
files.sort(key=lambda x: os.path.getmtime(os.path.join(BASE_DIR, x)), reverse=True)

if not files:
    st.info("No videos found.")
else:
    for f in files:
        file_path = os.path.join(BASE_DIR, f)
        
        st.divider()
        
        cols = st.columns([0.4, 0.4, 0.2])

        # Video player preview
        try:
            cols[0].video(file_path)
        except Exception:
            cols[0].warning("Cannot preview video")

        # Info
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        from datetime import datetime
        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        
        cols[1].write(f"**Name:** {f}")
        cols[1].write(f"**Path:** `{file_path}`")
        cols[1].write(f"**Size:** {file_size_mb:.2f} MB")
        cols[1].write(f"**Modified:** {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Download button
        with open(file_path, 'rb') as video_file:
            cols[1].download_button(
                label="⬇️ Download",
                data=video_file,
                file_name=f,
                mime="video/mp4",
                key=f"download_{f}"
            )

        # Delete
        delete_key = f"delete_{f}"
        if cols[2].button("🗑 Delete", key=delete_key):
            os.remove(file_path)
            st.success(f"Deleted {f}")
            st.rerun()