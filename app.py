from flask import Flask, request, jsonify, session
from flask_session import Session
from google import genai
from google.genai import types
import sqlite3
import time
import uuid
import os
from PIL import Image
from io import BytesIO
import base64
from celery import Celery
import logging
from werkzeug.exceptions import HTTPException

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379/0',
    CELERY_RESULT_BACKEND='redis://localhost:6379/0'
)
Session(app)

# Centralized Error Handler
@app.errorhandler(Exception)
def handle_exception(e):
    # Log the exception
    app.logger.error(f"An error occurred: {e}", exc_info=True)
    # Pass through HTTP exceptions
    if isinstance(e, HTTPException):
        return e
    # Handle non-HTTP exceptions
    return jsonify({
        "error": {
            "name": type(e).__name__,
            "message": str(e)
        }
    }), 500

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

celery = make_celery(app)
client = genai.Client()  # API key from env GEMINI_API_KEY

# SQLite setup
def init_db():
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chats (session_id TEXT, message TEXT, role TEXT)''')
    conn.commit()
    conn.close()

init_db()

@celery.task
def generate_video_task(prompt, model):
    """Celery task to generate video asynchronously."""
    operation = client.models.generate_videos(model=model, prompt=prompt)

    while not operation.done:
        time.sleep(10)
        operation = client.operations.get(operation)

    generated_video = operation.response.generated_videos[0]
    video_filename = f"{uuid.uuid4()}.mp4"
    client.files.download(file=generated_video.video)
    generated_video.video.save(video_filename)
    return video_filename

@app.route('/start_session', methods=['POST'])
def start_session():
    try:
        session['id'] = str(uuid.uuid4())
        return jsonify({'session_id': session['id']})
    except Exception as e:
        handle_exception(e)


@app.route('/list_models', methods=['GET'])
def list_models():
    try:
        chat_models = []
        image_models = []
        video_models = []
        for m in client.models.list_models():
            if 'generateContent' in m.supported_generation_methods:
                chat_models.append(m.name)
            if 'generateImages' in m.supported_generation_methods or 'imagen' in m.name:
                image_models.append(m.name)
            if 'generateVideos' in m.supported_generation_methods or 'veo' in m.name:
                video_models.append(m.name)

        return jsonify({
            'chat_models': sorted(list(set(chat_models))),
            'image_models': sorted(list(set(image_models))),
            'video_models': sorted(list(set(video_models)))
        })
    except Exception as e:
        handle_exception(e)

@app.route('/model_info', methods=['GET'])
def model_info():
    try:
        model_data = [
            {"Model Family": "Gemini 2.5 Pro", "Example Variants": "gemini-2.5-pro, gemini-2.5-pro-preview", "Capabilities": "Chat, function calling, code execution, grounding", "Input Modalities": "Text, images, video, audio, PDF", "Output Modalities": "Text", "Token Limits (Input/Output)": "1,048,576 / 65,536", "Notes": "Advanced reasoning; knowledge cutoff Jan 2025."},
            {"Model Family": "Gemini 2.5 Flash", "Example Variants": "gemini-2.5-flash, gemini-2.5-flash-preview-09-2025", "Capabilities": "Chat, function calling, structured outputs", "Input Modalities": "Text, images, video, audio", "Output Modalities": "Text", "Token Limits (Input/Output)": "1,048,576 / 65,536", "Notes": "Faster variant; supports search grounding."},
            {"Model Family": "Gemini 2.5 Flash Image", "Example Variants": "gemini-2.5-flash-image, gemini-2.5-flash-image-preview", "Capabilities": "Image generation, chat", "Input Modalities": "Images, text", "Output Modalities": "Images, text", "Token Limits (Input/Output)": "32,768 / 32,768", "Notes": "Uses Imagen under the hood for text-to-image."},
            {"Model Family": "Gemini 2.5 Flash Live", "Example Variants": "gemini-2.5-flash-native-audio-preview-09-2025", "Capabilities": "Live chat, audio generation", "Input Modalities": "Audio, video, text", "Output Modalities": "Audio, text", "Token Limits (Input/Output)": "128,000 / 8,000", "Notes": "For real-time interactions."},
            {"Model Family": "Gemini 2.0 Flash", "Example Variants": "gemini-2.0-flash, gemini-2.0-flash-exp", "Capabilities": "Chat, function calling", "Input Modalities": "Audio, images, video, text", "Output Modalities": "Text", "Token Limits (Input/Output)": "1,048,576 / 8,192", "Notes": "Experimental thinking support."},
            {"Model Family": "Imagen 4", "Example Variants": "imagen-4.0-generate-001, imagen-4.0-ultra-generate-001", "Capabilities": "High-fidelity image generation", "Input Modalities": "Text", "Output Modalities": "Images (1-4)", "Token Limits (Input/Output)": "480 / N/A", "Notes": "Supports aspect ratios, person generation controls, labels; English prompts only."},
            {"Model Family": "Imagen 3", "Example Variants": "imagen-3.0-generate-002", "Capabilities": "Image generation", "Input Modalities": "Text", "Output Modalities": "Images (up to 4)", "Token Limits (Input/Output)": "N/A / N/A", "Notes": "Basic text-to-image; includes SynthID watermark."},
            {"Model Family": "Veo 3.1", "Example Variants": "veo-3.1-generate-preview, veo-3.1-fast-generate-preview", "Capabilities": "Video generation with audio", "Input Modalities": "Text, images, videos", "Output Modalities": "Video (MP4, 4-8s)", "Token Limits (Input/Output)": "1,024 / 1 video", "Notes": "Supports extensions, reference images, advanced controls; asynchronous."},
            {"Model Family": "Veo 3", "Example Variants": "veo-3.0-generate-001, veo-3.0-fast-generate-001", "Capabilities": "Video generation with audio", "Input Modalities": "Text, images", "Output Modalities": "Video (MP4)", "Token Limits (Input/Output)": "1,024 / 1 video", "Notes": "720p/1080p; includes SynthID."},
            {"Model Family": "Veo 2", "Example Variants": "veo-2.0-generate-001", "Capabilities": "Silent video generation", "Input Modalities": "Text, images", "Output Modalities": "Video (silent)", "Token Limits (Input/Output)": "N/A / up to 2 videos", "Notes": "Older variant; up to 20MB input images."}
        ]
        return jsonify(model_data)
    except Exception as e:
        handle_exception(e)

from flask import Response

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        session_id = data['session_id']
        model_name = data.get('model', 'gemini-2.5-pro')
        user_message = data['message']

        # Load history
        conn = sqlite3.connect('chat_history.db')
        c = conn.cursor()
        c.execute('SELECT role, message FROM chats WHERE session_id=? ORDER BY rowid', (session_id,))
        history = [{'role': row[0], 'parts': [{'text': row[1]}]} for row in c.fetchall()]

        # Create chat with history
        chat_session = client.chats.create(model=model_name, history=history)

        # Get streaming response
        response_stream = chat_session.send_message(message=user_message, stream=True)

        def generate():
            # Accumulate the full response to save to DB
            full_response_text = ""
            for chunk in response_stream:
                full_response_text += chunk.text
                yield chunk.text

            # Save messages after streaming is complete
            c.execute('INSERT INTO chats VALUES (?, ?, ?)', (session_id, user_message, 'user'))
            c.execute('INSERT INTO chats VALUES (?, ?, ?)', (session_id, full_response_text, 'model'))
            conn.commit()
            conn.close()

        return Response(generate(), mimetype='text/plain')
    except Exception as e:
        handle_exception(e)

@app.route('/generate_image', methods=['POST'])
def generate_image():
    try:
        data = request.json
        prompt = data['prompt']
        model = data.get('model', 'imagen-4.0-generate-001')
        num_images = data.get('num_images', 1)
        aspect_ratio = data.get('aspect_ratio', '1:1')

        response = client.models.generate_images(
            model=model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=num_images,
                aspect_ratio=aspect_ratio
            )
        )

        images = []
        for img in response.generated_images:
            buffered = BytesIO()
            img.image.save(buffered, format="PNG")
            images.append(base64.b64encode(buffered.getvalue()).decode('utf-8'))

        return jsonify({'images': images})
    except Exception as e:
        handle_exception(e)

@app.route('/generate_video', methods=['POST'])
def generate_video():
    try:
        data = request.json
        prompt = data['prompt']
        model = data.get('model', 'veo-3.1-generate-preview')

        task = generate_video_task.delay(prompt, model)

        return jsonify({'task_id': task.id})
    except Exception as e:
        handle_exception(e)

@app.route('/video_status/<task_id>', methods=['GET'])
def video_status(task_id):
    try:
        task = generate_video_task.AsyncResult(task_id)
        if task.state == 'PENDING':
            response = {
                'state': task.state,
                'status': 'Pending...'
            }
        elif task.state != 'FAILURE':
            response = {
                'state': task.state,
                'status': 'Task complete!',
                'result': task.info,
            }
        else:
            response = {
                'state': task.state,
                'status': str(task.info),
            }
        return jsonify(response)
    except Exception as e:
        handle_exception(e)

if __name__ == '__main__':
    app.run(debug=True)
