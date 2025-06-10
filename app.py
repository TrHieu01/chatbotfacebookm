from flask import Flask, request, jsonify
import requests
import os
import logging
from dotenv import load_dotenv
from openai import OpenAI

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load biến môi trường từ .env
load_dotenv()

app = Flask(__name__)

# Kiểm tra các biến môi trường bắt buộc
required_vars = ["VERIFY_TOKEN", "PAGE_ACCESS_TOKEN", "OPENAI_API_KEY"]
for var in required_vars:
    if not os.getenv(var):
        raise ValueError(f"Missing required environment variable: {var}")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# Cache cho context data
context_cache = None

def load_context():
    """Load context từ file data.txt với cache"""
    global context_cache
    if context_cache is None:
        try:
            with open("data.txt", "r", encoding="utf-8") as f:
                context_cache = f.read().strip()
                logger.info("Context loaded successfully")
        except FileNotFoundError:
            logger.warning("data.txt not found, using empty context")
            context_cache = ""
        except Exception as e:
            logger.error(f"Error loading context: {e}")
            context_cache = ""
    return context_cache

# Xác minh webhook từ Facebook
@app.route('/webhook', methods=['GET'])
def verify():
    try:
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully")
            return challenge, 200
        else:
            logger.warning("Webhook verification failed")
            return "Verification token mismatch", 403
    except Exception as e:
        logger.error(f"Error in webhook verification: {e}")
        return "Internal server error", 500

# Nhận tin nhắn từ người dùng
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        
        if not data or 'entry' not in data:
            return "Invalid data", 400
            
        for entry in data['entry']:
            if 'messaging' not in entry:
                continue
                
            for messaging_event in entry['messaging']:
                if 'message' in messaging_event and 'text' in messaging_event['message']:
                    sender_id = messaging_event['sender']['id']
                    message_text = messaging_event['message']['text']
                    
                    logger.info(f"Received message from {sender_id}: {message_text}")
                    
                    # Kiểm tra tin nhắn không rỗng
                    if message_text.strip():
                        reply = get_ai_reply(message_text)
                        if reply:
                            send_message(sender_id, reply)
                        else:
                            send_message(sender_id, "Xin lỗi, tôi không thể xử lý tin nhắn của bạn lúc này.")
        
        return "ok", 200
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return "Internal server error", 500

# Gửi câu trả lời từ GPT
def get_ai_reply(user_message):
    try:
        context = load_context()
        
        # Giới hạn độ dài context và user message
        max_context_length = 2000
        max_message_length = 500
        
        if len(context) > max_context_length:
            context = context[:max_context_length] + "..."
            
        if len(user_message) > max_message_length:
            user_message = user_message[:max_message_length] + "..."
        
        prompt = f"""Dựa vào dữ liệu sau:
{context}

Người dùng hỏi: {user_message}

Hãy trả lời ngắn gọn, chính xác và hữu ích. Nếu không tìm thấy thông tin phù hợp trong dữ liệu, hãy nói rõ và đưa ra lời khuyên chung."""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Bạn là một trợ lý AI hữu ích, trả lời bằng tiếng Việt một cách ngắn gọn và dễ hiểu."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.7
        )
        
        reply = response.choices[0].message.content.strip()
        logger.info(f"AI reply generated: {reply[:50]}...")
        return reply
        
    except Exception as e:
        logger.error(f"Error getting AI reply: {e}")
        return "Xin lỗi, tôi đang gặp sự cố kỹ thuật. Vui lòng thử lại sau."

# Gửi tin nhắn về Facebook
def send_message(recipient_id, message_text):
    try:
        url = 'https://graph.facebook.com/v19.0/me/messages'
        headers = {'Content-Type': 'application/json'}
        params = {'access_token': PAGE_ACCESS_TOKEN}
        
        # Giới hạn độ dài tin nhắn (Facebook Messenger limit ~2000 chars)
        if len(message_text) > 1900:
            message_text = message_text[:1900] + "..."
        
        payload = {
            'recipient': {'id': recipient_id},
            'message': {'text': message_text}
        }
        
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Message sent successfully to {recipient_id}")
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error sending message: {e}")
    except Exception as e:
        logger.error(f"Error sending message: {e}")

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "messenger-bot"}), 200

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# Chạy app
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
