from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import sqlite3
import os
import logging
from datetime import datetime

# 載入環境變數
load_dotenv()

# 初始化 Flask 和 LINE Bot
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

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
    
    logging.info(f"Request body: {body}")
    logging.info(f"Signature: {signature}")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("Invalid signature. Request aborted.")
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    
    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}
    
    # 重置用戶狀態並執行相應功能
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
            reply = "請輸入「新增」、「查詢」或「刪除」來管理食材。"
    
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
    app.run()