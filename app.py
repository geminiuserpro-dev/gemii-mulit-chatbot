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

app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

client = genai.Client()  # API key from env GEMINI_API_KEY

# SQLite setup
def init_db():
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chats (session_id TEXT, message TEXT, role TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/start_session', methods=['POST'])
def start_session():
    session['id'] = str(uuid.uuid4())
    return jsonify({'session_id': session['id']})

@app.route('/list_models', methods=['GET'])
def list_models():
    models = [m.name for m in client.models.list_models()]
    return jsonify(models)

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
    chat = client.chats.create(model=model_name, history=history)

    # Send message
    response = chat.send_message(message=user_message)

    # Save messages
    c.execute('INSERT INTO chats VALUES (?, ?, ?)', (session_id, user_message, 'user'))
    c.execute('INSERT INTO chats VALUES (?, ?, ?)', (session_id, response.text, 'model'))
    conn.commit()
    conn.close()

    return jsonify({'response': response.text})

@app.route('/generate_image', methods=['POST'])
def generate_image():
    data = request.json
    prompt = data['prompt']
    model = data.get('model', 'imagen-4.0-generate-001')
    num_images = data.get('num_images', 1)
    aspect_ratio = data.get('aspect_ratio', '1:1')  # Example optional param

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

    operation = client.models.generate_videos(model=model, prompt=prompt)

    while not operation.done:
        time.sleep(10)
        operation = client.operations.get(operation)

    generated_video = operation.response.generated_videos[0]
    client.files.download(file=generated_video.video)
    generated_video.video.save("generated_video.mp4")

    return jsonify({'video_path': 'generated_video.mp4'})  # In prod, use cloud storage URL

if __name__ == '__main__':
    app.run(debug=True)
