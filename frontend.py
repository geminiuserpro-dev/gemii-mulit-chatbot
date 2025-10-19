import streamlit as st
import requests
import base64
from PIL import Image
from io import BytesIO

BACKEND_URL = "http://localhost:5000"

if 'session_id' not in st.session_state:
    response = requests.post(f"{BACKEND_URL}/start_session")
    st.session_state['session_id'] = response.json()['session_id']

st.title("Gemini App: Chat, Images, Videos")

models = requests.get(f"{BACKEND_URL}/list_models").json()
selected_model = st.selectbox("Select Model", models)

st.subheader("Chat")
user_input = st.text_input("Your message")
if st.button("Send"):
    response = requests.post(f"{BACKEND_URL}/chat", json={
        'session_id': st.session_state['session_id'],
        'model': selected_model,
        'message': user_input
    })
    st.write("Response:", response.json()['response'])

st.subheader("Generate Image")
img_prompt = st.text_input("Image prompt")
if st.button("Generate Image"):
    response = requests.post(f"{BACKEND_URL}/generate_image", json={
        'prompt': img_prompt,
        'model': 'imagen-4.0-generate-001'
    })
    for img_base64 in response.json()['images']:
        img = Image.open(BytesIO(base64.b64decode(img_base64)))
        st.image(img)

st.subheader("Generate Video with Veo")
video_prompt = st.text_input("Video prompt")
if st.button("Generate Video"):
    response = requests.post(f"{BACKEND_URL}/generate_video", json={
        'prompt': video_prompt,
        'model': 'veo-3.1-generate-preview'
    })
    st.video(response.json()['video_path'])
