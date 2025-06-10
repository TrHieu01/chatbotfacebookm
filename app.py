from flask import Flask, request
import requests
import openai
import os
from dotenv import load_dotenv

# Load biến môi trường từ .env
load_dotenv()

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

# Xác minh webhook từ Facebook
@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification token mismatch", 403

# Nhận tin nhắn từ người dùng
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if 'entry' in data:
        for entry in data['entry']:
            for messaging_event in entry['messaging']:
                if 'message' in messaging_event:
                    sender_id = messaging_event['sender']['id']
                    message_text = messaging_event['message'].get('text')
                    if message_text:
                        reply = get_ai_reply(message_text)
                        send_message(sender_id, reply)
    return "ok", 200

# Gửi câu trả lời từ GPT
def get_ai_reply(user_message):
    with open("data.txt", "r", encoding="utf-8") as f:
        context = f.read()
    prompt = f"Dữ liệu sau:\n{context}\n\nNgười dùng hỏi: {user_message}\nTrả lời ngắn gọn, dễ hiểu:"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    return response['choices'][0]['message']['content'].strip()

# Gửi tin nhắn về Facebook
def send_message(recipient_id, message_text):
    url = 'https://graph.facebook.com/v16.0/me/messages'
    headers = {'Content-Type': 'application/json'}
    params = {'access_token': PAGE_ACCESS_TOKEN}
    payload = {
        'recipient': {'id': recipient_id},
        'message': {'text': message_text}
    }
    requests.post(url, headers=headers, params=params, json=payload)

# Chạy app
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
