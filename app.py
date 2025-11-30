import streamlit as st
import os
import uuid
import requests
import json
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import time
import subprocess

# Try to load .env file if available (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed (fine for Streamlit Cloud)
    pass

# Load ElevenLabs API key from environment or Streamlit secrets
try:
    # Try environment variable first (from .env or system)
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
    
    # If not in environment, try Streamlit secrets (cloud deployment)
    if not ELEVENLABS_API_KEY:
        ELEVENLABS_API_KEY = st.secrets.get("ELEVENLABS_API_KEY", "")
except:
    # Fallback if secrets not configured
    ELEVENLABS_API_KEY = ""


# -------------------------------------------------------
# PROJECT SETUP
# -------------------------------------------------------

st.set_page_config(page_title="AI Video Script Editor", layout="wide")

BASE_DIR = "assets"
IMAGE_DIR = os.path.join(BASE_DIR, "images")
VOICE_DIR = os.path.join(BASE_DIR, "voice")
AVATAR_DIR = os.path.join(BASE_DIR, "avatar")
VIDEO_DIR = "video"
TEMP_DIR = os.path.join(BASE_DIR, "temp")

# Create all necessary folders
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(VOICE_DIR, exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


# -------------------------------------------------------
# HELPERS
# -------------------------------------------------------

def is_valid_url(url: str) -> bool:
    import re
    return bool(re.match(r"^(https?://)[A-Za-z0-9.-]+", url))


def download_image(url: str, folder: str = IMAGE_DIR) -> str:
    """Download URL → saved into folder → return local path."""
    resp = requests.get(url, timeout=8)
    resp.raise_for_status()

    ext = url.split("?")[0].split(".")[-1].lower()
    if ext not in ["jpg", "jpeg", "png", "webp"]:
        ext = "png"

    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join(folder, filename)

    with open(path, "wb") as f:
        f.write(resp.content)

    return path


def save_upload(file, folder: str = IMAGE_DIR) -> str:
    """Save uploaded file into folder → return local path."""
    ext = file.name.split(".")[-1].lower()
    if ext not in ["jpg", "jpeg", "png", "webp"]:
        ext = "png"

    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join(folder, filename)

    with open(path, "wb") as f:
        f.write(file.getbuffer())

    return path


# -------------------------------------------------------
# ELEVENLABS TEXT-TO-SPEECH
# -------------------------------------------------------

def text_to_speech_elevenlabs(text: str, voice_id: str, api_key: str, output_path: str) -> str:
    """
    Convert text to speech using ElevenLabs API
    """
    
    # Validate API key
    if not api_key or api_key.strip() == "":
        raise ValueError("ElevenLabs API key is missing or empty")
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key.strip()  # Ensure no whitespace
    }
    
    data = {
        "text": text,
        "model_id": "eleven_v3",  # v3 model supports Thai language
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True
        }
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path
    except requests.exceptions.HTTPError as e:
        # Provide more detailed error information
        error_msg = f"ElevenLabs API Error: {e}"
        if e.response is not None:
            try:
                error_detail = e.response.json()
                error_msg += f"\nDetails: {error_detail}"
            except:
                error_msg += f"\nResponse: {e.response.text}"
        raise Exception(error_msg)


def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds using ffprobe"""
    # Convert Windows backslashes to forward slashes for ffprobe
    audio_path_normalized = audio_path.replace('\\', '/')
    
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_path_normalized
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        st.warning(f"Could not get audio duration with ffprobe: {e}")
        # Fallback: estimate based on text length (will be passed separately)
        # For now, use file size estimation
        try:
            file_size = os.path.getsize(audio_path)
            estimated = file_size / 16000  # Rough estimate for MP3
            st.info(f"Using estimated duration: {estimated:.1f}s")
            return estimated
        except:
            # Ultimate fallback
            return 3.0


def create_silence_audio(duration: float, output_path: str) -> str:
    """Create silent audio file of specified duration"""
    try:
        # Normalize path for ffmpeg
        output_path_normalized = output_path.replace('\\', '/')
        
        cmd = [
            'ffmpeg',
            '-f', 'lavfi',
            '-i', f'anullsrc=r=44100:cl=stereo',
            '-t', str(duration),
            '-q:a', '9',
            '-acodec', 'libmp3lame',
            '-y',
            output_path_normalized
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        st.error(f"Failed to create silence: {e}")
        return None


def merge_audio_with_timestamps(audio_segments: list, total_duration: float, output_path: str) -> str:
    """
    Merge audio files with proper timing using FFmpeg
    audio_segments: list of {'path': str, 'start_time': float, 'duration': float}
    """
    if not audio_segments:
        return None
    
    try:
        # Normalize all paths for ffmpeg (use forward slashes)
        output_path_normalized = output_path.replace('\\', '/')
        
        # Build filter complex for mixing audio at specific timestamps
        inputs = []
        filter_parts = []
        
        for i, segment in enumerate(audio_segments):
            # Normalize path for ffmpeg
            segment_path_normalized = segment['path'].replace('\\', '/')
            inputs.extend(['-i', segment_path_normalized])
            # Add delay to each audio segment
            delay_ms = int(segment['start_time'] * 1000)
            filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")
        
        # Mix all delayed audio streams
        mix_inputs = ''.join([f"[a{i}]" for i in range(len(audio_segments))])
        filter_parts.append(f"{mix_inputs}amix=inputs={len(audio_segments)}:duration=longest[outa]")
        
        filter_complex = ';'.join(filter_parts)
        
        cmd = [
            'ffmpeg',
            '-y',
            *inputs,
            '-filter_complex', filter_complex,
            '-map', '[outa]',
            '-t', str(total_duration),
            output_path_normalized
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
        
    except subprocess.CalledProcessError as e:
        st.error(f"Failed to merge audio: {e.stderr}")
        return None


def add_audio_to_video(video_path: str, audio_path: str, output_path: str) -> str:
    """Add audio track to video using ffmpeg"""
    if not audio_path or not os.path.exists(audio_path):
        st.warning("No audio file to add to video")
        return video_path
    
    try:
        # Normalize paths for ffmpeg (forward slashes)
        video_path_normalized = video_path.replace('\\', '/')
        audio_path_normalized = audio_path.replace('\\', '/')
        output_path_normalized = output_path.replace('\\', '/')
        
        cmd = [
            'ffmpeg',
            '-i', video_path_normalized,
            '-i', audio_path_normalized,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-shortest',
            '-y',
            output_path_normalized
        ]
        result = subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        st.error(f"Failed to add audio to video: {e.stderr.decode() if e.stderr else str(e)}")
        return video_path


def convert_to_h264(input_path: str, output_path: str) -> str:
    """Convert video to H.264 codec for web compatibility"""
    try:
        # Normalize paths
        input_normalized = input_path.replace('\\', '/')
        output_normalized = output_path.replace('\\', '/')
        
        cmd = [
            'ffmpeg',
            '-i', input_normalized,
            '-c:v', 'libx264',  # H.264 codec
            '-preset', 'medium',  # Encoding speed
            '-crf', '23',  # Quality (lower = better, 23 is default)
            '-pix_fmt', 'yuv420p',  # Pixel format for compatibility
            '-c:a', 'aac',  # Audio codec
            '-b:a', '192k',  # Audio bitrate
            '-movflags', '+faststart',  # Enable streaming
            '-y',
            output_normalized
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        st.error(f"Failed to convert video: {e.stderr.decode() if e.stderr else str(e)}")
        return input_path


# -------------------------------------------------------
# VIDEO GENERATION
# -------------------------------------------------------

def create_professional_frame(image_path: str, width: int, height: int) -> np.ndarray:
    """
    Create a professional frame with image in upper portion and space below for text
    """
    # Load the image
    img = Image.open(image_path).convert("RGB")
    original_width, original_height = img.size
    
    # Reserve bottom 25% of frame for text
    text_space_height = int(height * 0.25)
    available_height = height - text_space_height
    
    # Calculate scaling to fit the image in upper portion (use 90% of available space - larger)
    max_fit_width = int(width * 0.8)
    max_fit_height = int(available_height * 0.90)  # Increased from 0.85 to 0.90
    
    # Calculate scale to fit within bounds
    scale = min(max_fit_width / original_width, max_fit_height / original_height)
    new_width = int(original_width * scale)
    new_height = int(original_height * scale)
    
    # Resize main image with high quality
    main_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Create blurred background
    # Scale image to fill entire frame for background
    bg_scale = max(width / original_width, height / original_height)
    bg_width = int(original_width * bg_scale)
    bg_height = int(original_height * bg_scale)
    bg_img = img.resize((bg_width, bg_height), Image.Resampling.LANCZOS)
    
    # Center crop the background
    left = (bg_width - width) // 2
    top = (bg_height - height) // 2
    bg_img = bg_img.crop((left, top, left + width, top + height))
    
    # Apply heavy blur to background
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=40))
    
    # Darken the background slightly for better contrast
    bg_array = np.array(bg_img).astype(float)
    bg_array = bg_array * 0.6  # Darken to 60%
    bg_img = Image.fromarray(bg_array.astype(np.uint8))
    
    # Paste main image in UPPER portion (centered horizontally, positioned lower in upper area)
    x_offset = (width - new_width) // 2
    # Center vertically in upper portion, then push down a bit
    y_offset = (available_height - new_height) // 2 + int(available_height * 0.15)  # Push down 15%
    bg_img.paste(main_img, (x_offset, y_offset))
    
    # Convert to numpy array for OpenCV
    frame = cv2.cvtColor(np.array(bg_img), cv2.COLOR_RGB2BGR)
    
    return frame


def add_title_to_frame(frame, text, font_path=None):
    """Add title text to the bottom of frame - same style as subtitles but larger"""
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    
    # Larger font for title
    try:
        font = ImageFont.truetype("./fonts/THSarabunNew-Bold.ttf", 120)  # Reduced from 200
        st.success("✅ Title font loaded: 120px")
    except Exception as e:
        st.error(f"❌ Title font failed: {e}")
        font = ImageFont.load_default()
    
    st.info(f"Font object: {font}")
    
    # Word wrap
    height, width = frame.shape[:2]
    max_width = width - 300
    
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        try:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]
        except:
            line_width = len(test_line) * 60
        
        if line_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    
    # Line height proportional to font size
    line_height = 156  # 120 * 1.3
    
    # Position text in the LOWER 25% space (not at very bottom)
    # Start text at 75% of frame height (beginning of lower space)
    lower_space_start = int(height * 0.73)  # Start a bit higher (was 0.75)
    total_text_height = len(lines) * line_height
    
    # Center text vertically within the lower space
    lower_space_height = int(height * 0.27)  # Adjusted to match (was 0.25)
    y_offset = lower_space_start + (lower_space_height - total_text_height) // 2
    
    # Draw text with shadow
    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
        except:
            text_width = len(line) * 60
        
        x = (width - text_width) // 2
        
        # Shadow
        for offset in range(1, 4):
            draw.text((x + offset, y_offset + offset), line, font=font, fill=(0, 0, 0))
        
        # WHITE text
        draw.text((x, y_offset), line, font=font, fill=(255, 255, 255))
        y_offset += line_height
    
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def add_avatar_to_frame(frame, voice_profile: str, character_enabled: bool) -> np.ndarray:
    """
    Add PNGTuber avatar to bottom-right corner of frame
    """
    if not character_enabled:
        return frame
    
    # Determine which avatar to use
    if voice_profile == "looknarm":
        avatar_filename = "looknarm.png"
    elif voice_profile == "santi":
        avatar_filename = "santi.png"
    else:
        return frame  # No avatar for custom voices
    
    avatar_path = os.path.join(AVATAR_DIR, avatar_filename)
    
    # Check if avatar exists
    if not os.path.exists(avatar_path):
        return frame
    
    try:
        # Load avatar with transparency
        avatar = Image.open(avatar_path).convert("RGBA")
        
        # Resize avatar to reasonable size (e.g., 15% of frame height)
        frame_height, frame_width = frame.shape[:2]
        avatar_height = int(frame_height * 0.15)
        aspect_ratio = avatar.size[0] / avatar.size[1]
        avatar_width = int(avatar_height * aspect_ratio)
        avatar = avatar.resize((avatar_width, avatar_height), Image.Resampling.LANCZOS)
        
        # Convert frame to PIL for compositing
        frame_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        
        # Position avatar in bottom-right corner with padding
        padding = 20
        x_pos = frame_width - avatar_width - padding
        y_pos = frame_height - avatar_height - padding
        
        # Paste avatar with transparency
        frame_pil.paste(avatar, (x_pos, y_pos), avatar)
        
        # Convert back to OpenCV format
        frame_with_avatar = cv2.cvtColor(np.array(frame_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
        
        return frame_with_avatar
    
    except Exception as e:
        st.warning(f"Failed to add avatar: {e}")
        return frame


def add_subtitle_to_frame(frame, text, font_path=None):
    """Add subtitle text to the bottom of frame with clean styling"""
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    
    # Subtitle font size (smaller than title)
    font_size = 60  # Reduced from 80
    
    # Use font from ./fonts/ directory
    try:
        font = ImageFont.truetype("./fonts/THSarabunNew-Bold.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    # Word wrap for subtitles
    height, width = frame.shape[:2]
    max_width = width - 300
    
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        try:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]
        except:
            line_width = len(test_line) * 35
        
        if line_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    
    # Line height proportional to font size (same as title)
    line_height = int(font_size * 1.3)
    
    # Position text in the LOWER 25% space
    lower_space_start = int(height * 0.73)  # Start a bit higher (was 0.75)
    total_text_height = len(lines) * line_height
    
    # Center text vertically within the lower space
    lower_space_height = int(height * 0.27)  # Adjusted to match (was 0.25)
    y_offset = lower_space_start + (lower_space_height - total_text_height) // 2
    
    # Draw text with shadow
    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
        except:
            text_width = len(line) * (font_size // 2)
        
        x = (width - text_width) // 2
        
        # Draw multiple shadow layers for better visibility without outline look
        # This creates a soft glow effect
        for offset in range(1, 4):  # 3 layers of shadow
            draw.text((x + offset, y_offset + offset), line, font=font, fill=(0, 0, 0))
        
        # Draw white text on top
        draw.text((x, y_offset), line, font=font, fill=(255, 255, 255))
        y_offset += line_height
    
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def create_video_from_cells(cells, settings, elevenlabs_api_key: str, output_path="output.mp4"):
    """
    Generate video from cells with:
    1. Thumbnail + Title intro
    2. Images stay until next image
    3. Text becomes subtitles + voice over
    """
    
    width, height = 1920, 1080
    fps = 24
    
    # Create temporary video without audio
    temp_video_path = os.path.join(TEMP_DIR, f"temp_video_{uuid.uuid4().hex[:8]}.mp4")
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video = cv2.VideoWriter(temp_video_path, fourcc, fps, (width, height))
    
    # Voice ID mapping
    voice_map = {
        "looknarm": st.session_state.get("looknarm_voice_id", "DGS95EuFRpKb6qGTgktO"),
        "santi": st.session_state.get("santi_voice_id", "44NdXk4X8FxnONM4FmXN"),
        "custom": st.session_state.get("custom_voice_id", ""),
    }
    
    voice_profile = settings.get("voice_profile", "looknarm")
    voice_id = voice_map.get(voice_profile)
    character_enabled = settings.get("character_enabled", False)
    
    # Don't generate voice if custom is selected but no ID provided
    if voice_profile == "custom" and not voice_id:
        st.warning("Custom voice selected but no Voice ID provided. Skipping voice generation.")
        voice_id = None
    
    # Track audio files and their timings
    audio_segments = []
    current_time = 0.0
    
    # ===== 1. INTRO: Thumbnail + Title (5 seconds) =====
    thumbnail_path = settings.get("thumbnail_path", "")
    title = settings.get("title", "Untitled Video")
    
    intro_duration = 5.0
    
    if thumbnail_path and os.path.exists(thumbnail_path):
        # Use same professional frame as content
        intro_bg = create_professional_frame(thumbnail_path, width, height)
        
        # Add title as subtitle (same position as subtitles, just larger font)
        intro_frame_with_title = add_title_to_frame(intro_bg, title)
        
        # Show intro for 5 seconds
        for _ in range(int(intro_duration * fps)):
            video.write(intro_frame_with_title)
        
        current_time += intro_duration
    
    # ===== 2. PROCESS CELLS =====
    current_image_frame = None
    
    # Pre-scan to find first image if text comes before any image
    first_image_path = None
    for cell in cells:
        if cell["type"] == "image" and cell.get("image_path"):
            first_image_path = cell["image_path"]
            break
    
    # If we have a first image, use it as the initial frame
    if first_image_path:
        current_image_frame = create_professional_frame(first_image_path, width, height)
    
    for idx, cell in enumerate(cells):
        
        if cell["type"] == "image" and cell.get("image_path"):
            # Load new image with professional blurred background
            try:
                current_image_frame = create_professional_frame(cell["image_path"], width, height)
                st.info(f"✓ Loaded image for cell {idx+1}")
            except Exception as e:
                st.warning(f"Failed to load image cell {idx+1}: {e}")
        
        elif cell["type"] == "text" and cell.get("content"):
            text_content = cell["content"]
            
            # Generate voice if enabled
            audio_path = None
            audio_duration = 3.0  # Default duration
            
            if voice_id and elevenlabs_api_key:
                try:
                    audio_filename = f"voice_{idx}_{uuid.uuid4().hex[:8]}.mp3"
                    audio_path = os.path.join(VOICE_DIR, audio_filename)
                    
                    text_to_speech_elevenlabs(
                        text_content,
                        voice_id,
                        elevenlabs_api_key,
                        audio_path
                    )
                    
                    audio_duration = get_audio_duration(audio_path)
                    
                    # Track audio segment with timing
                    audio_segments.append({
                        'path': audio_path,
                        'start_time': current_time,
                        'duration': audio_duration
                    })
                    
                    st.info(f"✓ Generated voice for text cell {idx+1} ({audio_duration:.1f}s)")
                    
                except Exception as e:
                    st.warning(f"Voice generation failed for cell {idx+1}: {e}")
                    audio_duration = len(text_content.split()) * 0.5  # Estimate: 0.5s per word
            else:
                # Estimate duration based on text length
                audio_duration = len(text_content.split()) * 0.5
            
            # Show current image with subtitle for the duration of audio
            if current_image_frame is not None:
                frame_with_subtitle = add_subtitle_to_frame(
                    current_image_frame.copy(),
                    text_content
                )
                # Add PNGTuber avatar if enabled
                frame_with_avatar = add_avatar_to_frame(frame_with_subtitle, voice_profile, character_enabled)
                
                num_frames = int(audio_duration * fps)
                for _ in range(num_frames):
                    video.write(frame_with_avatar)
            else:
                # No image available - create a default background
                # Use thumbnail as fallback if available
                if thumbnail_path and os.path.exists(thumbnail_path):
                    current_image_frame = create_professional_frame(thumbnail_path, width, height)
                    frame_with_subtitle = add_subtitle_to_frame(
                        current_image_frame.copy(),
                        text_content
                    )
                    # Add PNGTuber avatar if enabled
                    frame_with_avatar = add_avatar_to_frame(frame_with_subtitle, voice_profile, character_enabled)
                else:
                    # Last resort: black background with text
                    img = Image.new('RGB', (width, height), (0, 0, 0))
                    frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGR2RGB)
                    frame_with_subtitle = add_subtitle_to_frame(frame, text_content)
                    # Add PNGTuber avatar if enabled
                    frame_with_avatar = add_avatar_to_frame(frame_with_subtitle, voice_profile, character_enabled)
                
                num_frames = int(audio_duration * fps)
                for _ in range(num_frames):
                    video.write(frame_with_avatar)
            
            current_time += audio_duration
    
    video.release()
    
    total_duration = current_time
    
    # ===== 3. MERGE AUDIO AND VIDEO =====
    if audio_segments:
        st.info(f"Merging {len(audio_segments)} audio track(s)...")
        
        # Merge all audio with proper timestamps
        merged_audio_path = os.path.join(TEMP_DIR, f"merged_audio_{uuid.uuid4().hex[:8]}.mp3")
        final_audio = merge_audio_with_timestamps(audio_segments, total_duration, merged_audio_path)
        
        if final_audio:
            # Add audio to video
            st.info("Adding audio to video...")
            temp_with_audio = os.path.join(TEMP_DIR, f"temp_with_audio_{uuid.uuid4().hex[:8]}.mp4")
            add_audio_to_video(temp_video_path, final_audio, temp_with_audio)
            
            # Convert to H.264 for web compatibility
            st.info("Converting to web-compatible format...")
            convert_to_h264(temp_with_audio, output_path)
            
            # Cleanup temp files
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
            if os.path.exists(merged_audio_path):
                os.remove(merged_audio_path)
            if os.path.exists(temp_with_audio):
                os.remove(temp_with_audio)
            
            return output_path
        else:
            # Audio merge failed, return video without audio (still convert to H.264)
            st.info("Converting to web-compatible format...")
            convert_to_h264(temp_video_path, output_path)
            os.remove(temp_video_path)
            return output_path
    else:
        # No audio, convert temp video to H.264
        st.info("Converting to web-compatible format...")
        convert_to_h264(temp_video_path, output_path)
        os.remove(temp_video_path)
        return output_path


# -------------------------------------------------------
# INITIAL STATE MODELS
# -------------------------------------------------------

def new_image_cell():
    return {
        "type": "image",
        "image_mode": "upload",
        "raw_url": "",
        "image_path": "",
        "image_filename": "",
        "uploaded_meta": None,
    }


def new_text_cell():
    return {
        "type": "text",
        "content": "",
    }


if "cells" not in st.session_state:
    st.session_state.cells = []

if "settings" not in st.session_state:
    st.session_state.settings = {
        "title": "",
        "thumbnail_path": "",
        "thumbnail_url": "",
        "voice_profile": "looknarm",
        "character_enabled": False,
    }

if "looknarm_voice_id" not in st.session_state:
    st.session_state.looknarm_voice_id = "DGS95EuFRpKb6qGTgktO"

if "santi_voice_id" not in st.session_state:
    st.session_state.santi_voice_id = "44NdXk4X8FxnONM4FmXN"

if "custom_voice_id" not in st.session_state:
    st.session_state.custom_voice_id = ""

# Track processed file uploads to prevent duplicates on rerun
if "processed_uploads" not in st.session_state:
    st.session_state.processed_uploads = set()


# -------------------------------------------------------
# SETTINGS PANEL
# -------------------------------------------------------

with st.expander("📌 Video Settings (Required)", expanded=True):

    # Show API key status
    if ELEVENLABS_API_KEY:
        st.success(f"✅ ElevenLabs API Key loaded (ends with: ...{ELEVENLABS_API_KEY[-4:]})")
    else:
        st.error("❌ ElevenLabs API Key not found")
        st.info("💡 Add your API key in one of these ways:")
        st.info("• **Local**: Create .env file with ELEVENLABS_API_KEY=your_key_here")
        st.info("• **Streamlit Cloud**: Add ELEVENLABS_API_KEY in app Settings → Secrets")

    # Title
    st.session_state.settings["title"] = st.text_input(
        "Video Title (required)",
        st.session_state.settings.get("title", "")
    )

    # Thumbnail
    st.write("### Thumbnail Image (Required)")

    thumb_mode = st.radio(
        "Thumbnail Source",
        ["Upload Image", "From URL", "By Filename"],
        key="thumb_mode"
    )

    if thumb_mode == "Upload Image":
        up = st.file_uploader(
            "Upload Thumbnail",
            type=["jpg", "jpeg", "png", "webp"],
            key="thumb_upload"
        )
        if up:
            # Create unique identifier for this file
            file_id = f"thumb_{up.name}_{up.size}"
            
            # Only process if we haven't seen this exact file before
            if file_id not in st.session_state.processed_uploads:
                p = save_upload(up, folder=IMAGE_DIR)
                st.session_state.settings["thumbnail_path"] = p
                st.session_state.processed_uploads.add(file_id)
                st.success("Thumbnail uploaded to images folder.")
            elif st.session_state.settings.get("thumbnail_path"):
                # File already processed, just show status
                st.info("✓ Thumbnail already loaded")

    elif thumb_mode == "From URL":
        url = st.text_input(
            "Thumbnail URL",
            st.session_state.settings.get("thumbnail_url", ""),
            key="thumb_url_input"
        )
        st.session_state.settings["thumbnail_url"] = url

        if st.button("Download Thumbnail from URL") and url.strip():
            if is_valid_url(url):
                try:
                    # Create unique ID to prevent duplicates
                    url_id = f"thumb_url_{url}"
                    if url_id not in st.session_state.processed_uploads:
                        p = download_image(url, folder=IMAGE_DIR)
                        st.session_state.settings["thumbnail_path"] = p
                        st.session_state.processed_uploads.add(url_id)
                        st.success("Thumbnail downloaded to images folder.")
                    else:
                        st.info("✓ This URL already downloaded")
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Invalid URL")
    
    else:  # By Filename
        filename = st.text_input(
            "Thumbnail Filename (must be in images folder)",
            st.session_state.settings.get("thumbnail_filename", ""),
            key="thumb_filename_input",
            help="Enter just the filename, e.g., 'thumbnail.png'"
        )
        st.session_state.settings["thumbnail_filename"] = filename
        
        if filename.strip():
            full_path = os.path.join(IMAGE_DIR, filename.strip())
            if os.path.exists(full_path):
                st.session_state.settings["thumbnail_path"] = full_path
                st.success(f"✓ Found: {filename}")
            else:
                st.error(f"❌ File not found: {filename}")
                st.info(f"Looking in: {IMAGE_DIR}")

    tp = st.session_state.settings.get("thumbnail_path", "")
    if tp and os.path.exists(tp):
        st.image(tp, width=300, caption="Current Thumbnail")

    # Voice Selection (hidden IDs in backend)
    st.write("### Narrator Voice")

    label_to_id = {
        "Prof. Looknarm": "looknarm",
        "Prof. Santi": "santi",
        "Custom Voice ID": "custom",
    }
    id_to_label = {v: k for k, v in label_to_id.items()}

    current_voice = st.session_state.settings.get("voice_profile", "looknarm")
    current_label = id_to_label.get(current_voice, "Prof. Looknarm")

    chosen_label = st.radio(
        "Choose default narration voice:",
        ["Prof. Looknarm", "Prof. Santi", "Custom Voice ID"],
        index=["Prof. Looknarm", "Prof. Santi", "Custom Voice ID"].index(current_label),
        key="voice_radio"
    )

    st.session_state.settings["voice_profile"] = label_to_id[chosen_label]
    
    # Show custom voice ID input only if Custom is selected
    if chosen_label == "Custom Voice ID":
        custom_id = st.text_input(
            "Enter Custom Voice ID",
            value=st.session_state.get("custom_voice_id", ""),
            key="custom_voice_input",
            help="Enter your ElevenLabs voice ID"
        )
        st.session_state.custom_voice_id = custom_id

    # PNGTuber toggle - only show for professors, not custom
    if st.session_state.settings["voice_profile"] in ["looknarm", "santi"]:
        st.write("### PNGTuber Character Avatar")
        st.session_state.settings["character_enabled"] = st.checkbox(
            "Enable character avatar overlay",
            value=st.session_state.settings.get("character_enabled", False),
            key="character_checkbox"
        )
        st.caption("Avatar image will be added in the video generator, not here.")
    else:
        # Disable character for custom voice
        st.session_state.settings["character_enabled"] = False


# -------------------------------------------------------
# CELLS EDITOR
# -------------------------------------------------------

st.title("📒 Video Script Notebook")

for i, cell in enumerate(st.session_state.cells):

    label = f"🖼 Image Cell {i+1}" if cell["type"] == "image" else f"📝 Text Cell {i+1}"

    with st.expander(label, expanded=False):

        c = st.columns([0.1, 0.1, 0.8])

        if c[0].button("❌", key=f"del_{i}"):
            del st.session_state.cells[i]
            st.rerun()

        if c[1].button("⬆️", key=f"up_{i}", disabled=i == 0):
            st.session_state.cells[i-1], st.session_state.cells[i] = (
                st.session_state.cells[i],
                st.session_state.cells[i-1]
            )
            st.rerun()

        if cell["type"] == "image":

            mode_label_map = {
                "upload": "Upload Image",
                "url": "From URL", 
                "name": "By Filename"
            }
            
            current_mode = cell.get("image_mode", "upload")
            current_label = mode_label_map.get(current_mode, "Upload Image")

            selected = st.radio(
                "Image Source",
                ["Upload Image", "From URL", "By Filename"],
                index=["Upload Image", "From URL", "By Filename"].index(current_label),
                key=f"imgsrc_{i}"
            )
            
            # Update mode based on selection
            if selected == "Upload Image":
                cell["image_mode"] = "upload"
            elif selected == "From URL":
                cell["image_mode"] = "url"
            else:
                cell["image_mode"] = "name"

            if cell["image_mode"] == "upload":
                file = st.file_uploader(
                    "Upload Image",
                    type=["jpg", "jpeg", "png", "webp"],
                    key=f"imgupload_{i}"
                )

                if file:
                    # Create unique identifier for this file
                    file_id = f"cell_{i}_{file.name}_{file.size}"
                    
                    # Check if this is a new file or if cell doesn't have image yet
                    if file_id not in st.session_state.processed_uploads or not cell.get("image_path"):
                        cell["image_path"] = save_upload(file, folder=IMAGE_DIR)
                        st.session_state.processed_uploads.add(file_id)
                        # Store metadata to track this file
                        cell["uploaded_meta"] = (file.name, file.size)
                        st.success("Saved new image")
                    elif cell.get("image_path"):
                        # File already processed
                        st.info("✓ Image already loaded")

                if cell.get("image_path"):
                    st.image(cell["image_path"], width=300)

            elif cell["image_mode"] == "url":
                url = st.text_input(
                    "Image URL",
                    cell.get("raw_url", ""),
                    key=f"url_{i}"
                )
                cell["raw_url"] = url

                if st.button("Download from URL", key=f"dl_{i}") and url.strip():
                    if is_valid_url(url):
                        try:
                            # Create unique ID for this URL to prevent duplicates
                            url_id = f"url_{i}_{url}"
                            if url_id not in st.session_state.processed_uploads:
                                cell["image_path"] = download_image(url, folder=IMAGE_DIR)
                                st.session_state.processed_uploads.add(url_id)
                                st.success("Image downloaded")
                            else:
                                st.info("✓ This URL already downloaded")
                        except Exception as e:
                            st.error(str(e))
                    else:
                        st.error("Invalid URL")

                if cell.get("image_path"):
                    st.image(cell["image_path"], width=300)
            
            else:  # name mode
                filename = st.text_input(
                    "Image Filename (must be in images folder)",
                    cell.get("image_filename", ""),
                    key=f"filename_{i}",
                    help="Enter just the filename, e.g., 'myimage.png'"
                )
                cell["image_filename"] = filename
                
                if filename.strip():
                    full_path = os.path.join(IMAGE_DIR, filename.strip())
                    if os.path.exists(full_path):
                        cell["image_path"] = full_path
                        st.success(f"✓ Found: {filename}")
                        st.image(full_path, width=300)
                    else:
                        st.error(f"❌ File not found: {filename}")
                        st.info(f"Looking in: {IMAGE_DIR}")

        else:
            cell["content"] = st.text_area(
                "Text (Narration + Subtitles)",
                cell.get("content", ""),
                height=150,
                key=f"text_{i}"
            )


# -------------------------------------------------------
# ADD CELLS
# -------------------------------------------------------

st.write("---")
b1, b2 = st.columns(2)

if b1.button("🖼 Add Image Cell"):
    st.session_state.cells.append(new_image_cell())
    st.rerun()

if b2.button("📝 Add Text Cell"):
    st.session_state.cells.append(new_text_cell())
    st.rerun()

st.write("---")


# -------------------------------------------------------
# EXPORT & VIDEO GENERATION
# -------------------------------------------------------

st.subheader("📤 Export & Generate")

col1, col2 = st.columns(2)

with col1:
    st.write("#### Export Script JSON")
    if st.button("📋 Generate JSON", use_container_width=True):
        output = {
            "settings": st.session_state.settings,
            "cells": st.session_state.cells
        }
        
        json_str = json.dumps(output, indent=2)
        
        st.download_button(
            "💾 Download JSON",
            json_str,
            file_name="script.json",
            mime="application/json",
            use_container_width=True
        )
        
        with st.expander("Preview JSON"):
            st.json(output)

with col2:
    st.write("#### Generate Video")
    if st.button("🎬 Create Video", type="primary", use_container_width=True):
        
        errors = []
        
        if not st.session_state.settings.get("title"):
            errors.append("Video title is required")
        
        if not st.session_state.settings.get("thumbnail_path"):
            errors.append("Thumbnail is required")
        
        if not st.session_state.cells:
            errors.append("Add at least one cell")
        
        valid_cells = [
            c for c in st.session_state.cells 
            if (c["type"] == "image" and c.get("image_path")) 
            or (c["type"] == "text" and c.get("content"))
        ]
        
        if not valid_cells:
            errors.append("No valid cells found")
        
        # Check for voice
        voice_profile = st.session_state.settings.get("voice_profile", "looknarm")
        if voice_profile == "custom":
            if not st.session_state.get("custom_voice_id"):
                errors.append("Custom voice selected but no Voice ID provided")
            elif not ELEVENLABS_API_KEY:
                errors.append("ElevenLabs API key not configured (check .env or Streamlit secrets)")
        elif voice_profile in ["looknarm", "santi"]:
            if not ELEVENLABS_API_KEY:
                errors.append("ElevenLabs API key not configured (check .env or Streamlit secrets)")
        
        if errors:
            for err in errors:
                st.error(f"❌ {err}")
        else:
            video_path = None  # Initialize outside try block
            
            with st.spinner("🎥 Generating video with voice... This may take 2-5 minutes"):
                try:
                    timestamp = int(time.time())
                    video_filename = f"{st.session_state.settings['title'].replace(' ', '_')}_{timestamp}.mp4"
                    video_path = os.path.join(VIDEO_DIR, video_filename)
                    
                    create_video_from_cells(
                        st.session_state.cells,
                        st.session_state.settings,
                        ELEVENLABS_API_KEY,
                        output_path=video_path
                    )
                    
                    st.success("✅ Video generated successfully!")
                    
                    video_size = os.path.getsize(video_path) / (1024 * 1024)
                    st.info(f"📊 Video: {video_filename} | Size: {video_size:.2f} MB")
                    
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
                    with st.expander("Show details"):
                        st.exception(e)
                    video_path = None  # Reset on error
            
            # Show download and preview OUTSIDE the spinner
            if video_path and os.path.exists(video_path):
                st.write("---")
                
                # Download button
                with open(video_path, "rb") as f:
                    st.download_button(
                        "📥 Download Video",
                        f,
                        file_name=os.path.basename(video_path),
                        mime="video/mp4",
                        use_container_width=True
                    )
                
                st.write("")  # Add spacing
                
                # Video preview
                st.write("### 🎬 Video Preview")
                try:
                    st.video(video_path)
                except Exception as e:
                    st.error(f"Could not preview video: {e}")
                    st.info(f"Video saved at: {video_path}")

st.write("---")
st.caption("💡 Images stay on screen until next image. Text becomes subtitles + voice narration.")