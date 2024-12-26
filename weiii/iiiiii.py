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
generativeai.configure(api_key=os.getenv('KEY'))

# 初始化 Flask 和 LINE Bot
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

user_states = {}

# 初始化資料庫
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
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}

    # 食材管理功能
    if user_message == "新增":
        user_states[user_id] = {"state": "add_name", "data": {}}
        reply = "請告訴我要新增的食材名稱和有效日期（格式：名稱1,日期1;名稱2,日期2）："
    elif user_message == "查詢":
        user_states[user_id] = {"state": None, "data": {}}
        ingredients = get_all_ingredients()
        if ingredients:
            reply = "\n".join([f"{index + 1}. {row[1]} (有效日期: {row[2]})" for index, row in enumerate(ingredients)])
        else:
            reply = "目前沒有任何食材記錄。"
    elif user_message == "刪除":
        user_states[user_id] = {"state": "delete", "data": {}}
        reply = "請輸入要刪除的食材 ID（多個 ID 請用空白分隔）："
    
    # 如果訊息不是新增、查詢或刪除，則進行與 Google Generative AI 的對話
    else:
        state = user_states[user_id]["state"]
        if state == "add_name":
            ingredients = user_message.split(';')
            errors = []
            for ingredient in ingredients:
                try:
                    name, expiration_date = ingredient.split(',')
                    if validate_date(expiration_date.strip()):
                        add_ingredient(name.strip(), expiration_date.strip())
                    else:
                        errors.append(f"日期格式錯誤：{expiration_date.strip()}")
                except ValueError:
                    errors.append(f"格式錯誤：{ingredient}")
            if errors:
                reply = "以下食材新增失敗：\n" + "\n".join(errors)
            else:
                reply = "已成功新增所有食材：\n" + "\n".join([f"{name.strip()}, {expiration_date.strip()}" for name, expiration_date in [ingredient.split(',') for ingredient in ingredients]])
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "delete":
            try:
                ingredient_ids = [int(id.strip()) for id in user_message.split()]
                delete_ingredients(ingredient_ids)
                reindex_ingredients()
                reply = f"已成功刪除食材 ID：{' '.join(map(str, ingredient_ids))}"
            except ValueError:
                reply = "請輸入有效的食材 ID。"
            user_states[user_id] = {"state": None, "data": {}}
        else:
            # 這裡使用 Google Generative AI 進行對話
            try:
                model = generativeai.GenerativeModel('gemini-2.0-flash-exp')
                response = model.generate_content(user_message)
                reply = response.text
            except Exception as e:
                reply = f"AI 發生錯誤：{str(e)}"

    # 回覆訊息
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

def validate_date(date_text):
    try:
        datetime.strptime(date_text, '%Y-%m-%d')
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
