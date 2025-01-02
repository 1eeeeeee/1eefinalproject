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
    
    # 食材管理
    if user_message == "新增":
        user_states[user_id] = {"state": "add_name", "data": {}}
        reply = "請告訴我要新增的食材名稱："
    elif user_states[user_id]["state"] == "add_name":
        user_states[user_id]["data"]["name"] = user_message
        user_states[user_id]["state"] = "add_date"
        reply = "請告訴我要新增的食材有效日期（格式：YYYY-MM-DD）："
    elif user_states[user_id]["state"] == "add_date":
        user_states[user_id]["data"]["date"] = user_message
        if validate_date(user_message):
            name = user_states[user_id]["data"]["name"]
            date = user_states[user_id]["data"]["date"]
            add_ingredient(name, date)
            reply = f"已新增食材：{name}（有效日期：{date}）"
            user_states[user_id] = {"state": None, "data": {}}
        else:
            reply = "日期格式錯誤，請重新輸入有效日期（格式：YYYY-MM-DD）："
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
    elif user_states[user_id]["state"] == "delete":
        ids = list(map(int, user_message.split()))
        delete_ingredients(ids)
        reply = f"已刪除食材 ID：{'、'.join(map(str, ids))}"
        user_states[user_id] = {"state": None, "data": {}}
    elif user_message == "修改":
        user_states[user_id] = {"state": "modify_id", "data": {}}
        reply = "請輸入要修改的食材 ID："
    elif user_states[user_id]["state"] == "modify_id":
        user_states[user_id]["data"]["id"] = user_message
        user_states[user_id]["state"] = "modify_field"
        reply = "請告訴我要修改的項目（1.名稱 2.日期）："
    elif user_states[user_id]["state"] == "modify_field":
        user_states[user_id]["data"]["field"] = user_message
        if user_message == "1":
            user_states[user_id]["state"] = "modify_name"
            reply = "請輸入新的名稱："
        elif user_message == "2":
            user_states[user_id]["state"] = "modify_date"
            reply = "請輸入新的有效日期（格式：YYYY-MM-DD）："
    elif user_states[user_id]["state"] == "modify_name":
        ingredient_id = user_states[user_id]["data"]["id"]
        new_name = user_message
        modify_ingredient_name(ingredient_id, new_name)
        reply = f"已修改食材 ID {ingredient_id} 的名稱為：{new_name}"
        user_states[user_id] = {"state": None, "data": {}}
    elif user_states[user_id]["state"] == "modify_date":
        ingredient_id = user_states[user_id]["data"]["id"]
        new_date = user_message
        if validate_date(new_date):
            modify_ingredient_date(ingredient_id, new_date)
            reply = f"已修改食材 ID {ingredient_id} 的有效日期為：{new_date}"
            user_states[user_id] = {"state": None, "data": {}}
        else:
            reply = "日期格式錯誤，請重新輸入有效日期（格式：YYYY-MM-DD）："
    else:
        try:
            model = generativeai.GenerativeModel('gemini-2.0-flash-exp')
            response = model.generate_content(user_message)
            reply = response.text
        except Exception as e:
            reply = f"AI 發生錯誤：{str(e)}"
    
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

def modify_ingredient_name(ingredient_id, new_name):
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE ingredients SET name = ? WHERE id = ?', (new_name, ingredient_id))
    conn.commit()
    conn.close()

def modify_ingredient_date(ingredient_id, new_date):
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE ingredients SET expiration_date = ? WHERE id = ?', (new_date, ingredient_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)