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

app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379/0',
    CELERY_RESULT_BACKEND='redis://localhost:6379/0'
)
Session(app)

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
    session['id'] = str(uuid.uuid4())
    return jsonify({'session_id': session['id']})

@app.route('/list_models', methods=['GET'])
def list_models():
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

from flask import Response

# ... (keep existing imports)

@app.route('/chat', methods=['POST'])
def chat():
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

@app.route('/generate_image', methods=['POST'])
def generate_image():
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

@app.route('/generate_video', methods=['POST'])
def generate_video():
    data = request.json
    prompt = data['prompt']
    model = data.get('model', 'veo-3.1-generate-preview')

    task = generate_video_task.delay(prompt, model)

    return jsonify({'task_id': task.id})

@app.route('/video_status/<task_id>', methods=['GET'])
def video_status(task_id):
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

if __name__ == '__main__':
    app.run(debug=True)
