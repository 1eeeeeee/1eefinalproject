from dotenv import load_dotenv
import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as generativeai

# 載入環境變數
load_dotenv()

# 初始化 Google Generative AI
generativeai.configure(api_key=os.getenv('key'))

# 初始化 Flask 和 LINE Bot
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

@app.route("/callback", methods=['POST'])
def callback():
    # 確認請求有效性
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text

    try:
        # 使用 Google Generative AI 生成回覆
        model = generativeai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(user_message)
        reply_text = response.text
    except Exception as e:
        reply_text = f"AI 發生錯誤：{str(e)}"

    # 傳送回覆訊息
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
