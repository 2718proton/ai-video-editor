import streamlit as st
import json
import re

st.set_page_config(page_title="AI Video Script Editor", layout="wide")


# -------------------------------------------------------
# Helper Validators
# -------------------------------------------------------

def is_valid_url(url: str) -> bool:
    pattern = re.compile(
        r'^(https?://)'
        r'([A-Za-z0-9.-]+)'
        r'(:\d+)?'
        r'(\/.*)?$'
    )
    return bool(pattern.match(url))


def verify_section(text: str):
    if not text.strip():
        return ["Section is empty."]
    return []


def verify_scene(scene):
    errors = []

    if not scene["name"].strip():
        errors.append("Scene name is empty.")

    if scene["image_mode"] != "url":
        errors.append("Image mode must be 'url' only.")

    if not scene["image_data"].strip():
        errors.append("Image URL is empty.")
    elif not is_valid_url(scene["image_data"].strip()):
        errors.append("Invalid image URL format.")

    if not scene["content"].strip():
        errors.append("Scene content is empty.")

    return errors


# -------------------------------------------------------
# Application UI
# -------------------------------------------------------

st.title("AI Video Script Editor (INI-style Format)")

# -------------------------------------------------------
# SETTINGS SECTION INPUT
# -------------------------------------------------------

st.header("Settings Editor")

default_settings = """[settings]
- user: looknarm
- character: true
"""

settings_text = st.text_area(
    "Settings (INI-style)",
    default_settings,
    height=160
)

def parse_settings(text):
    result = {}
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        if line.startswith("- "):
            try:
                key, value = line[2:].split(":", 1)
                key = key.strip()
                value = value.strip()

                # convert true/false
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False

                result[key] = value
            except:
                pass
    return result


settings_errors = verify_section(settings_text)
if settings_errors:
    st.error("Invalid settings format.")
settings = parse_settings(settings_text)


# -------------------------------------------------------
# ADDING A SCENE
# -------------------------------------------------------

st.header("Add a Scene")

scene_name = st.text_input("Scene name")
image_url = st.text_input("Image URL")
content = st.text_area("Scene content", height=140)

if st.button("Add scene"):
    new_scene = {
        "name": scene_name,
        "image_mode": "url",
        "image_data": image_url,
        "content": content
    }

    errors = verify_scene(new_scene)

    if errors:
        st.error("Scene could not be added:")
        for err in errors:
            st.write("- " + err)
    else:
        if "scenes" not in st.session_state:
            st.session_state.scenes = []
        st.session_state.scenes.append(new_scene)
        st.success("Scene added.")


# -------------------------------------------------------
# CURRENT SCENES LIST
# -------------------------------------------------------

st.header("Current Scenes")

if "scenes" not in st.session_state or len(st.session_state.scenes) == 0:
    st.info("No scenes added yet.")
else:
    for i, scene in enumerate(st.session_state.scenes):
        with st.expander(f"Scene {i+1}: {scene['name']}"):
            st.write(f"[scene]")
            st.write(f"- name: {scene['name']}")
            st.write(f"- image_mode: {scene['image_mode']}")
            st.write(f"- image_data: {scene['image_data']}")
            st.write(f"- content: {scene['content']}")

            if st.button(f"Remove scene {i+1}", key=f"remove_scene_{i}"):
                st.session_state.scenes.pop(i)
                st.experimental_rerun()


# -------------------------------------------------------
# EXPORT OUTPUT
# -------------------------------------------------------

st.header("Export Script")

if st.button("Generate JSON Output"):
    if settings_errors:
        st.error("Cannot export. Fix settings format first.")
    elif "scenes" not in st.session_state or len(st.session_state.scenes) == 0:
        st.error("Cannot export. Add at least one scene.")
    else:
        output = {
            "settings": settings,
            "scenes": st.session_state.scenes
        }
        st.json(output)
        st.success("Export complete.")
