from dotenv import load_dotenv
import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as generativeai
import sqlite3
from datetime import datetime

# 載入環境變數
load_dotenv()

# 初始化 Google Generative AI
# generativeai.configure(api_key=os.getenv('KEY'))

# 初始化 Flask 和 LINE Bot
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
print("Loaded LINE_CHANNEL_ACCESS:", os.getenv('LINE_CHANNEL_ACCESS'))
print("Loaded LINE_CHANNEL_SECRET:", os.getenv('LINE_CHANNEL_SECRET'))

user_states = {}

def init_db():
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            expiration_date TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route("/callback", methods=['POST'])
def callback():
    # 確認請求來自 LINE 平台
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    
    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}
    
    state = user_states[user_id]["state"]
    
    if state is None:
        if user_message == "新增":
            user_states[user_id] = {"state": "ASK_INGREDIENT", "data": {}}
            reply = "請告訴我要新增的食材名稱："
        elif user_message == "查詢":
            ingredients = get_all_ingredients()
            if ingredients:
                reply = "\n".join([f"{index + 1}. {row[1]} (有效日期: {row[2]})" for index, row in enumerate(ingredients)])
            else:
                reply = "目前沒有任何食材記錄。"
        elif user_message == "刪除":
            user_states[user_id] = {"state": "delete", "data": {}}
            reply = "請輸入要刪除的食材 ID（多個 ID 請用空白分隔）："
        else:
            try:
                model = generativeai.GenerativeModel('gemini-2.0-flash-exp')
                response = model.generate_content(user_message)
                reply = response.text
            except Exception as e:
                reply = f"AI 發生錯誤：{str(e)}"
    elif state == "ASK_INGREDIENT":
        user_states[user_id]["data"]["ingredient"] = user_message
        user_states[user_id]["state"] = "ASK_EXPIRATION"
        reply = "請告訴我該食材的有效日期（格式：YYYY-MM-DD）："
    elif state == "ASK_EXPIRATION":
        expiration_date = user_message
        if validate_date(expiration_date):
            ingredient = user_states[user_id]["data"]["ingredient"]
            add_ingredient(ingredient, expiration_date)
            reply = f"已成功新增食材：{ingredient}，有效日期：{expiration_date}"
            user_states[user_id] = {"state": None, "data": {}}
        else:
            reply = "日期格式錯誤或日期已過期，請輸入有效日期（格式：YYYY-MM-DD）。"
    elif state == "delete":
        try:
            ingredient_ids = [int(id.strip()) for id in user_message.split()]
            delete_ingredients(ingredient_ids)
            reindex_ingredients()
            reply = f"已成功刪除食材 ID：{' '.join(map(str, ingredient_ids))}"
        except ValueError:
            reply = "請輸入有效的食材 ID。"
        user_states[user_id] = {"state": None, "data": {}}
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

def validate_date(date_text):
    try:
        date = datetime.strptime(date_text, '%Y-%m-%d')
        if date < datetime.now():
            return False
        return True
    except ValueError:
        return False

def get_all_ingredients():
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM ingredients ORDER BY id')
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_ingredient(name, expiration_date):
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO ingredients (name, expiration_date) VALUES (?, ?)', (name, expiration_date))
    conn.commit()
    conn.close()

def delete_ingredients(ids):
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.executemany('DELETE FROM ingredients WHERE id = ?', [(i,) for i in ids])
    conn.commit()
    conn.close()

def reindex_ingredients():
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM ingredients ORDER BY id')
    rows = cursor.fetchall()
    cursor.execute('DELETE FROM ingredients')
    for index, row in enumerate(rows, start=1):
        cursor.execute('INSERT INTO ingredients (id, name, expiration_date) VALUES (?, ?, ?)', (index, row[1], row[2]))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)