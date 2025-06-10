from flask import Flask, request
import requests
import openai

app = Flask(__name__)

VERIFY_TOKEN = "hius-bot"
PAGE_ACCESS_TOKEN = 'EAAZAekSjLEX8BOZBmsB6L06lAjlAHhZAg3TTMr7NMQfZB7Yf8wyhvnexRtmdsCIhJ4M7GDr0fj2owQwLtWpdZAjQ5oAZAwZCsSPNxZCnSby5025iKKgGeJ9FZCahoQXTL2gp9SVszGH0Y5wpzLsZBB3YzIZCduZB2m4SXZBxbS3TJV0RdXirxiCHaHZBg60rusXoSBniYr1phvCvZACylcz00gaYXKEZBo1xiwZDZD'
OPENAI_API_KEY = "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"

openai.api_key = OPENAI_API_KEY

# Webhook verification
@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification token mismatch", 403

# Nhận tin nhắn
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

def get_ai_reply(user_message):
    with open("data.txt", "r", encoding="utf-8") as f:
        context = f.read()
    prompt = f"Dữ liệu sau:\n{context}\n\nNgười dùng hỏi: {user_message}\nTrả lời ngắn gọn, dễ hiểu:"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    return response['choices'][0]['message']['content'].strip()

def send_message(recipient_id, message_text):
    url = 'https://graph.facebook.com/v16.0/me/messages'
    headers = {'Content-Type': 'application/json'}
    params = {'access_token': PAGE_ACCESS_TOKEN}
    payload = {
        'recipient': {'id': recipient_id},
        'message': {'text': message_text}
    }
    requests.post(url, headers=headers, params=params, json=payload)

if __name__ == "__main__":
    app.run(port=5000)
    
