from flask import Flask, request
import requests
import os
from dotenv import load_dotenv
from openai import OpenAI
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)

# Environment variables
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise

# Handle root endpoint
@app.route('/')
def home():
    logger.info("Received request to root endpoint")
    return "Webhook server is running", 200

# Verify webhook from Facebook
@app.route('/webhook', methods=['GET'])
def verify():
    try:
        mode = request.args.get("hub.mode")
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode == "subscribe" and verify_token == verify_token:
            logger.info("Webhook verification successful")
            return challenge, 200
        logger.warning("Webhook verification failed: Token mismatch")
        return "Verification token mismatch", 403
    except Exception as e:
        logger.error(f"Error in webhook verification: {e}")
        return "Error in verification", 500

# Handle incoming messages
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if not data or 'entry' not in data:
            logger.warning("Invalid webhook data received")
            return "Invalid data", 400

        for entry in data['entry']:
            for messaging_event in entry.get('messaging', []):
                if 'message' in messaging_event and 'text' in messaging_event['message']:
                    sender_id = messaging_event['sender']['id']
                    message_text = messaging_event['message']['text']
                    logger.info(f"Received message from {sender_id}: {message_text}")
                    reply = get_ai_reply(message_text)
                    send_message(sender_id, reply)
        return "ok", 200
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return "Error processing webhook", 500

# Generate AI reply using OpenAI
def get_ai_reply(user_message):
    try:
        with open("data.txt", "r", encoding="utf-8") as f:
            context = f.read()
        prompt = f"Dữ liệu sau:\n{context}\n\nNgười dùng hỏi: {user_message}\nTrả lời ngắn gọn, dễ hiểu:"
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        reply = response.choices[0].message.content.strip()
        logger.info(f"Generated AI reply: {reply}")
        return reply
    except FileNotFoundError:
        logger.error("data.txt file not found")
        return "Lỗi: Không tìm thấy dữ liệu bối cảnh."
    except Exception as e:
        logger.error(f"Error generating AI reply: {e}")
        return "Lỗi: Không thể tạo câu trả lời."

# Send message back to Facebook
def send_message(recipient_id, message_text):
    try:
        url = 'https://graph.facebook.com/v20.0/me/messages'
        headers = {'Content-Type': 'application/json'}
        params = {'access_token': PAGE_ACCESS_TOKEN}
        payload = {
            'recipient': {'id': recipient_id},
            'message': {'text': message_text[:2000]}
        }
        response = requests.post(url, headers=headers, params=params, json=payload)
        response.raise_for_status()
        logger.info(f"Message sent to {recipient_id}")
    except requests.RequestException as e:
        logger.error(f"Failed to send message to {recipient_id}: {e}")

# Run the app
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
