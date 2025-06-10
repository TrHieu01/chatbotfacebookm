from flask import Flask, request, jsonify
import requests
import os
import logging
from dotenv import load_dotenv
from openai import OpenAI
import threading
import time

# Cấu hình logging cho Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load biến môi trường từ .env (chỉ khi chạy local)
if os.path.exists('.env'):
    load_dotenv()
    logger.info("Loaded .env file")

app = Flask(__name__)

# Kiểm tra các biến môi trường bắt buộc
required_vars = ["VERIFY_TOKEN", "PAGE_ACCESS_TOKEN", "OPENAI_API_KEY"]
missing_vars = [var for var in required_vars if not os.getenv(var)]

if missing_vars:
    logger.error(f"Missing required environment variables: {missing_vars}")
    # Không raise error để Render có thể start service, sẽ báo lỗi khi sử dụng
else:
    logger.info("All required environment variables found")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Khởi tạo OpenAI client với error handling
client = None
if OPENAI_API_KEY:
    try:
        # Thử khởi tạo với cách đơn giản nhất
        client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client initialized successfully")
    except TypeError as e:
        logger.error(f"OpenAI client initialization failed with TypeError: {e}")
        # Thử khởi tạo với cách cũ hơn
        try:
            import openai
            openai.api_key = OPENAI_API_KEY
            logger.info("Using legacy OpenAI configuration")
            client = "legacy"  # Đánh dấu sử dụng legacy mode
        except Exception as e2:
            logger.error(f"Legacy OpenAI setup also failed: {e2}")
            client = None
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        client = None

# Cache cho context data
context_cache = None
context_last_modified = 0

def load_context():
    """Load context từ file data.txt với cache và file checking"""
    global context_cache, context_last_modified
    
    try:
        # Kiểm tra nếu file tồn tại
        if not os.path.exists("data.txt"):
            logger.warning("data.txt not found, creating empty file")
            with open("data.txt", "w", encoding="utf-8") as f:
                f.write("Tôi là chatbot hỗ trợ khách hàng. Tôi sẵn sàng giúp đỡ bạn!")
        
        # Kiểm tra thời gian modify của file
        current_modified = os.path.getmtime("data.txt")
        
        if context_cache is None or current_modified != context_last_modified:
            with open("data.txt", "r", encoding="utf-8") as f:
                context_cache = f.read().strip()
                context_last_modified = current_modified
                logger.info("Context loaded/reloaded successfully")
        
        return context_cache if context_cache else "Không có dữ liệu khả dụng."
        
    except Exception as e:
        logger.error(f"Error loading context: {e}")
        return "Dữ liệu tạm thời không khả dụng."

# Health check endpoint (quan trọng cho Render)
@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint cho Render"""
    try:
        status = {
            "status": "healthy",
            "service": "messenger-bot",
            "timestamp": time.time(),
            "environment_variables": {
                "VERIFY_TOKEN": "✓" if VERIFY_TOKEN else "✗",
                "PAGE_ACCESS_TOKEN": "✓" if PAGE_ACCESS_TOKEN else "✗",
                "OPENAI_API_KEY": "✓" if OPENAI_API_KEY else "✗"
            },
            "openai_client": "✓" if client else "✗",
            "data_file": "✓" if os.path.exists("data.txt") else "✗"
        }
        return jsonify(status), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# Xác minh webhook từ Facebook
@app.route('/webhook', methods=['GET'])
def verify():
    """Webhook verification cho Facebook"""
    try:
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        logger.info(f"Webhook verification attempt - Mode: {mode}, Token present: {bool(token)}")
        
        if not VERIFY_TOKEN:
            logger.error("VERIFY_TOKEN not configured")
            return "Server configuration error", 500
        
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully")
            return challenge, 200
        else:
            logger.warning(f"Webhook verification failed - Expected: {VERIFY_TOKEN}, Got: {token}")
            return "Verification token mismatch", 403
            
    except Exception as e:
        logger.error(f"Error in webhook verification: {e}")
        return "Internal server error", 500

# Nhận tin nhắn từ người dùng
@app.route('/webhook', methods=['POST'])
def webhook():
    """Xử lý tin nhắn từ Facebook Messenger"""
    try:
        data = request.get_json()
        
        if not data:
            logger.warning("Received empty webhook data")
            return "No data", 400
            
        logger.info(f"Webhook data received: {data}")
        
        if 'entry' not in data:
            logger.warning("No 'entry' field in webhook data")
            return "Invalid data format", 400
            
        for entry in data['entry']:
            if 'messaging' not in entry:
                continue
                
            for messaging_event in entry['messaging']:
                # Xử lý tin nhắn text
                if 'message' in messaging_event and 'text' in messaging_event['message']:
                    sender_id = messaging_event['sender']['id']
                    message_text = messaging_event['message']['text']
                    
                    logger.info(f"Processing message from {sender_id}: {message_text}")
                    
                    # Xử lý tin nhắn trong thread riêng để không block webhook
                    threading.Thread(
                        target=process_message_async,
                        args=(sender_id, message_text)
                    ).start()
                
                # Xử lý postback (nút bấm)
                elif 'postback' in messaging_event:
                    sender_id = messaging_event['sender']['id']
                    payload = messaging_event['postback']['payload']
                    
                    logger.info(f"Processing postback from {sender_id}: {payload}")
                    
                    threading.Thread(
                        target=process_postback_async,
                        args=(sender_id, payload)
                    ).start()
        
        return "ok", 200
        
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return "Internal server error", 500

def process_message_async(sender_id, message_text):
    """Xử lý tin nhắn bất đồng bộ"""
    try:
        if not message_text.strip():
            return
            
        reply = get_ai_reply(message_text)
        if reply:
            send_message(sender_id, reply)
        else:
            send_message(sender_id, "Xin lỗi, tôi không thể xử lý tin nhắn của bạn lúc này. Vui lòng thử lại sau.")
            
    except Exception as e:
        logger.error(f"Error in async message processing: {e}")
        send_message(sender_id, "Đã xảy ra lỗi kỹ thuật. Vui lòng thử lại sau.")

def process_postback_async(sender_id, payload):
    """Xử lý postback bất đồng bộ"""
    try:
        if payload == "GET_STARTED":
            welcome_msg = "Xin chào! Tôi là chatbot hỗ trợ. Bạn có thể hỏi tôi bất cứ điều gì!"
            send_message(sender_id, welcome_msg)
        else:
            reply = get_ai_reply(f"Người dùng đã chọn: {payload}")
            send_message(sender_id, reply)
            
    except Exception as e:
        logger.error(f"Error in async postback processing: {e}")

def get_ai_reply(user_message):
    """Tạo phản hồi từ AI"""
    try:
        if not client:
            logger.error("OpenAI client not available")
            return "Dịch vụ AI tạm thời không khả dụng."
        
        context = load_context()
        
        # Giới hạn độ dài để tránh vượt quá token limit
        max_context_length = 1500
        max_message_length = 400
        
        if len(context) > max_context_length:
            context = context[:max_context_length] + "..."
            
        if len(user_message) > max_message_length:
            user_message = user_message[:max_message_length] + "..."
        
        prompt = f"""Dựa vào thông tin sau:
{context}

Câu hỏi của khách hàng: {user_message}

Hãy trả lời một cách thân thiện, hữu ích và ngắn gọn. Nếu không tìm thấy thông tin phù hợp, hãy nói rõ và đưa ra lời khuyên chung."""

        # Xử lý cho cả new client và legacy mode
        if client == "legacy":
            # Sử dụng cách cũ
            import openai
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system", 
                        "content": "Bạn là trợ lý khách hàng thân thiện, chuyên nghiệp. Trả lời bằng tiếng Việt, ngắn gọn và hữu ích."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=250,
                temperature=0.7
            )
            reply = response.choices[0].message.content.strip()
        else:
            # Sử dụng client mới
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system", 
                        "content": "Bạn là trợ lý khách hàng thân thiện, chuyên nghiệp. Trả lời bằng tiếng Việt, ngắn gọn và hữu ích."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=250,
                temperature=0.7
            )
            reply = response.choices[0].message.content.strip()
        
        logger.info(f"AI reply generated successfully")
        return reply
        
    except Exception as e:
        logger.error(f"Error getting AI reply: {e}")
        return "Xin lỗi, tôi đang gặp sự cố kỹ thuật. Vui lòng thử lại sau ít phút."

def send_message(recipient_id, message_text):
    """Gửi tin nhắn qua Facebook Messenger"""
    try:
        if not PAGE_ACCESS_TOKEN:
            logger.error("PAGE_ACCESS_TOKEN not configured")
            return False
        
        url = 'https://graph.facebook.com/v19.0/me/messages'
        headers = {'Content-Type': 'application/json'}
        params = {'access_token': PAGE_ACCESS_TOKEN}
        
        # Chia tin nhắn dài thành nhiều phần
        max_length = 1900
        if len(message_text) > max_length:
            parts = [message_text[i:i+max_length] for i in range(0, len(message_text), max_length)]
            for part in parts:
                payload = {
                    'recipient': {'id': recipient_id},
                    'message': {'text': part}
                }
                requests.post(url, headers=headers, params=params, json=payload, timeout=10)
                time.sleep(0.5)  # Delay nhỏ giữa các message
        else:
            payload = {
                'recipient': {'id': recipient_id},
                'message': {'text': message_text}
            }
            
            response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"Message sent successfully to {recipient_id}")
                return True
            else:
                logger.error(f"Failed to send message: {response.status_code} - {response.text}")
                return False
                
    except requests.exceptions.Timeout:
        logger.error("Timeout sending message to Facebook")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error sending message: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    return jsonify({"error": "An unexpected error occurred"}), 500

# Khởi động ứng dụng
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask app on port {port}")
    
    # Render yêu cầu bind tới 0.0.0.0
    app.run(
        host="0.0.0.0", 
        port=port, 
        debug=False,
        threaded=True  # Quan trọng cho multi-threading
    )
