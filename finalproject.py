import google.generativeai as generativeai
import sqlite3
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import logging
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 初始化 Google Generative AI
generativeai.configure(api_key=os.getenv('KEY'))

# 初始化 Flask 和 LINE Bot
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 設定日誌紀錄
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

# 確保資料庫初始化
init_db()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    logging.debug(f"Received body: {body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("Invalid signature. Request aborted.")
        abort(400)
    except Exception as e:
        logging.error(f"處理訊息時發生錯誤: {e}")
        abort(500)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    logging.info(f"User ID: {user_id}, Message: {user_message}")

    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}

    state = user_states[user_id]["state"]

    # 食材管理
    if state is None:
        if user_message == "新增":
            user_states[user_id] = {"state": "add_name", "data": {}}
            reply = "請告訴我要新增的食材名稱："
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
        elif user_message == "修改":
            user_states[user_id] = {"state": "modify_id", "data": {}}
            reply = "請輸入要修改的食材 ID："
        else:
            reply = "請輸入「新增」、「查詢」、「刪除」或「修改」來管理食材。"
    elif state == "add_name":
        user_states[user_id]["data"]["name"] = user_message
        user_states[user_id]["state"] = "add_date"
        reply = "請告訴我要新增的食材有效日期（格式：YYYY-MM-DD）："
    elif state == "add_date":
        expiration_date = user_message
        if validate_date(expiration_date):
            name = user_states[user_id]["data"]["name"]
            add_ingredient(name, expiration_date)
            reply = f"已新增食材：{name}（有效日期：{expiration_date}）"
            user_states[user_id] = {"state": None, "data": {}}
        else:
            reply = "日期格式錯誤，請重新輸入有效日期（格式：YYYY-MM-DD）："
    elif state == "delete":
        try:
            ingredient_ids = [int(id.strip()) for id in user_message.split()]
            delete_ingredients(ingredient_ids)
            reindex_ingredients()
            reply = f"已成功刪除食材 ID：{' '.join(map(str, ingredient_ids))}"
        except ValueError:
            reply = "請輸入有效的食材 ID。"
        user_states[user_id] = {"state": None, "data": {}}
    elif state == "modify_id":
        try:
            ingredient_id = int(user_message)
            user_states[user_id]["data"]["id"] = ingredient_id
            user_states[user_id]["state"] = "modify_field"
            reply = "請選擇要修改的項目：1. 名稱 2. 日期"
        except ValueError:
            reply = "請輸入有效的食材 ID。"
    elif state == "modify_field":
        if user_message == "1":
            user_states[user_id]["state"] = "modify_name"
            reply = "請輸入新的食材名稱："
        elif user_message == "2":
            user_states[user_id]["state"] = "modify_date"
            reply = "請輸入新的有效日期 (格式：YYYY-MM-DD)："
        else:
            reply = "請選擇要修改的項目：1. 名稱 2. 日期"
    elif state == "modify_name":
        new_name = user_message
        ingredient_id = user_states[user_id]["data"].get("id")
        modify_ingredient_name(ingredient_id, new_name)
        reply = f"已成功修改食材 ID {ingredient_id} 的名稱為：{new_name}"
        user_states[user_id] = {"state": None, "data": {}}
    elif state == "modify_date":
        new_date = user_message
        ingredient_id = user_states[user_id]["data"].get("id")
        if validate_date(new_date):
            modify_ingredient_date(ingredient_id, new_date)
            reply = f"已成功修改食材 ID {ingredient_id} 的有效日期為：{new_date}"
        else:
            reply = "日期格式錯誤，請重新輸入 (格式：YYYY-MM-DD)。"
        user_states[user_id] = {"state": None, "data": {}}
    else:
        try:
            model = generativeai.GenerativeModel('gemini-2.0-flash-exp')
            response = model.generate_content(user_message)
            reply = response.text
        except Exception as e:
            reply = f"AI 發生錯誤：{str(e)}"
    
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
    except Exception as e:
        logging.error(f"回覆訊息時發生錯誤: {e}")

def validate_date(date_text):
    try:
        datetime.strptime(date_text, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def get_all_ingredients():
    try:
        conn = sqlite3.connect('ingredients.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM ingredients ORDER BY id')
        return cursor.fetchall()
    except sqlite3.Error as e:
        logging.error(f"查詢食材失敗: {e}")
        return []
    finally:
        conn.close()

def add_ingredient(name, expiration_date):
    try:
        conn = sqlite3.connect('ingredients.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO ingredients (name, expiration_date) VALUES (?, ?)', (name, expiration_date))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"新增食材失敗: {e}")
    finally:
        conn.close()

def delete_ingredients(ids):
    try:
        conn = sqlite3.connect('ingredients.db')
        cursor = conn.cursor()
        cursor.executemany('DELETE FROM ingredients WHERE id = ?', [(i,) for i in ids])
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"刪除食材失敗: {e}")
    finally:
        conn.close()

def modify_ingredient_name(ingredient_id, new_name):
    try:
        conn = sqlite3.connect('ingredients.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE ingredients SET name = ? WHERE id = ?', (new_name, ingredient_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"修改食材名稱失敗: {e}")
    finally:
        conn.close()

def modify_ingredient_date(ingredient_id, new_date):
    try:
        conn = sqlite3.connect('ingredients.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE ingredients SET expiration_date = ? WHERE id = ?', (new_date, ingredient_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"修改食材日期失敗: {e}")
    finally:
        conn.close()

def reindex_ingredients():
    try:
        conn = sqlite3.connect('ingredients.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM ingredients ORDER BY id')
        rows = cursor.fetchall()
        cursor.execute('DELETE FROM ingredients')
        for index, row in enumerate(rows, start=1):
            cursor.execute('INSERT INTO ingredients (id, name, expiration_date) VALUES (?, ?, ?)', (index, row[1], row[2]))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"重新編號食材失敗: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)