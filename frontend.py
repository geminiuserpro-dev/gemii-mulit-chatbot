import streamlit as st
import requests
import base64
from PIL import Image
from io import BytesIO
import time
import pandas as pd

BACKEND_URL = "http://localhost:5000"

# Function to handle requests and errors
def make_request(method, url, **kwargs):
    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()  # Raise an exception for bad status codes
        return response
    except requests.exceptions.RequestException as e:
        try:
            # Try to parse the JSON error response from the backend
            error_data = e.response.json()
            error_name = error_data.get('error', {}).get('name', 'Unknown Error')
            error_message = error_data.get('error', {}).get('message', 'No additional information.')
            st.error(f"A backend error occurred: {error_name}")
            st.error(f"Details: {error_message}")
        except (ValueError, AttributeError):
            # Fallback for non-JSON responses or other request errors
            st.error(f"An error occurred: {e}")
        return None

# Initialize session
if 'session_id' not in st.session_state:
    with st.spinner('Initializing session...'):
        response = make_request("post", f"{BACKEND_URL}/start_session")
        if response:
            st.session_state['session_id'] = response.json()['session_id']
        else:
            st.error("Could not initialize session. Please check if the backend is running.")
            st.stop() # Stop the app if we can't get a session

st.title("Gemini App: Chat, Images, Videos")

# Display model information
with st.expander("View Model Information"):
    model_info_response = make_request("get", f"{BACKEND_URL}/model_info")
    if model_info_response:
        df = pd.DataFrame(model_info_response.json())
        st.dataframe(df)
    else:
        st.warning("Could not fetch model information from the backend.")


# Fetch categorized models
with st.spinner('Fetching available models...'):
    models_response = make_request("get", f"{BACKEND_URL}/list_models")
    if models_response:
        models_data = models_response.json()
        chat_models = models_data.get('chat_models', [])
        image_models = models_data.get('image_models', [])
        video_models = models_data.get('video_models', [])
    else:
        chat_models, image_models, video_models = [], [], []
        st.warning("Could not fetch models from the backend.")

st.subheader("Chat")
selected_chat_model = st.selectbox("Select Chat Model", chat_models)
user_input = st.text_input("Your message")
if st.button("Send"):
    if user_input:
        with st.spinner('Thinking...'):
            response = make_request("post", f"{BACKEND_URL}/chat", json={
                'session_id': st.session_state['session_id'],
                'model': selected_chat_model,
                'message': user_input
            }, stream=True)

            if response:
                st.write("Response:")
                st.write_stream(response.iter_content(chunk_size=1024))
    else:
        st.warning("Please enter a message.")

st.subheader("Generate Image")
selected_image_model = st.selectbox("Select Image Model", image_models)
img_prompt = st.text_input("Image prompt")
if st.button("Generate Image"):
    if img_prompt:
        with st.spinner('Generating image...'):
            response = make_request("post", f"{BACKEND_URL}/generate_image", json={
                'prompt': img_prompt,
                'model': selected_image_model
            })
            if response:
                images_data = response.json()
                if images_data.get('images'):
                    for img_base64 in images_data['images']:
                        try:
                            img = Image.open(BytesIO(base64.b64decode(img_base64)))
                            st.image(img)
                        except Exception as e:
                            st.error(f"Could not display image: {e}")
                else:
                    st.error("Image generation failed or returned no images.")
    else:
        st.warning("Please enter an image prompt.")

st.subheader("Generate Video with Veo")
selected_video_model = st.selectbox("Select Video Model", video_models)
video_prompt = st.text_input("Video prompt")
if st.button("Generate Video"):
    if video_prompt:
        task_id = None
        with st.spinner('Requesting video generation...'):
            response = make_request("post", f"{BACKEND_URL}/generate_video", json={
                'prompt': video_prompt,
                'model': selected_video_model
            })
            if response:
                task_id = response.json().get('task_id')
                st.write(f"Video generation started with task ID: {task_id}")

        if task_id:
            with st.spinner('Waiting for video to be generated...'):
                while True:
                    status_response = make_request("get", f"{BACKEND_URL}/video_status/{task_id}")
                    if not status_response:
                        st.error("Could not get video status.")
                        break

                    status_data = status_response.json()
                    if status_data['state'] == 'SUCCESS':
                        st.video(status_data['result'])
                        break
                    elif status_data['state'] == 'FAILURE':
                        st.error("Video generation failed.")
                        st.error(status_data['status'])
                        break
                    elif status_data['state'] == 'PENDING':
                        pass # continue polling
                    else:
                        st.warning(f"Video generation in unknown state: {status_data['state']}")
                    time.sleep(5)
    else:
        st.warning("Please enter a video prompt.")
