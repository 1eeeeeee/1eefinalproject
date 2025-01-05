import os
import sqlite3
import logging
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as generativeai

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

# 使用者狀態
user_states = {}

# 資料庫檔案的路徑
DB_PATH = os.path.join(os.getcwd(), 'data', 'ingredients.db')  # 使用相對路徑

# 初始化資料庫
def init_db():
    try:
        if os.path.exists(DB_PATH):
            logging.info(f"舊的資料庫檔案已刪除：{DB_PATH}")
            os.remove(DB_PATH)

        conn = sqlite3.connect(DB_PATH)
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
        logging.info(f"已成功重新生成資料庫，路徑：{DB_PATH}")
    except Exception as e:
        logging.error(f"資料庫初始化時發生錯誤: {str(e)}")

init_db()

@app.route("/callback", methods=['POST'])
def callback():
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

    if user_message == "新增":
        user_states[user_id] = {"state": "add_name", "data": {}}
        reply = "請輸入要新增的食材名稱和有效日期：\n（例如：蘋果 2025/01/01）"
    elif user_message == "查詢":
        user_states[user_id] = {"state": None, "data": {}}
        ingredients = get_all_ingredients()
        if ingredients:
            reply = "\n".join([f"{row[0]}. {row[1]} (有效日期：{row[2]})" for row in ingredients])
        else:
            reply = "目前沒有任何食材記錄。"
    elif user_message == "刪除":
        user_states[user_id] = {"state": "delete", "data": {}}
        reply = "請輸入要刪除的食材ID（多個ID請用空白分隔）："
    elif user_message == "修改":
        ingredients = get_all_ingredients()
        if ingredients:
            user_states[user_id] = {"state": "modify_select_id", "data": {}}
            reply = "請選擇要修改的食材ID：\n" + "\n".join([f"{row[0]}. {row[1]} (有效日期：{row[2]})" for row in ingredients])
        else:
            reply = "目前沒有任何食材記錄。"
    elif user_message == "食譜":
        user_states[user_id] = {"state": "recipe", "data": {}}
        reply = "請輸入食材名稱（請用空白分隔）："
    else:
        state = user_states[user_id]["state"]
        if state == "add_name":
            ingredients = user_message.split(';')
            errors = []
            for ingredient in ingredients:
                try:
                    parts = ingredient.split()
                    if len(parts) != 2:
                        errors.append(f"格式錯誤：{ingredient}")
                        continue
                    name, expiration_date = parts
                    if validate_date(expiration_date.strip()):
                        add_ingredient(name.strip(), expiration_date.strip())
                    else:
                        errors.append(f"日期格式錯誤：{expiration_date.strip()}")
                except ValueError:
                    errors.append(f"格式錯誤：{ingredient}")
            if errors:
                reply = "以下食材新增失敗：\n" + "\n".join(errors)
            else:
                reply = "已成功新增：\n" + "\n".join([f"{name.strip()} {expiration_date.strip()}" for name, expiration_date in [ingredient.split() for ingredient in ingredients]])
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "delete":
            try:
                ingredient_ids = [int(id.strip()) for id in user_message.split()]
                delete_ingredients(ingredient_ids)
                reply = f"已成功刪除食材ID：{' '.join(map(str, ingredient_ids))}"
            except ValueError:
                reply = "請輸入有效的食材ID。"
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "modify_select_id":
            try:
                ingredient_id = int(user_message.strip())
                if check_ingredient_exists(ingredient_id):
                    user_states[user_id] = {"state": "modify_select_field", "data": {"id": ingredient_id}}
                    reply = "請選擇要修改的欄位：\n1. 名稱\n2. 有效日期"
                else:
                    reply = "該食材ID不存在，請重新輸入。"
            except ValueError:
                reply = "請輸入有效的食材ID。"
        elif state == "modify_select_field":
            if user_message == "1":
                user_states[user_id]["state"] = "modify_name"
                reply = "請輸入新的名稱："
            elif user_message == "2":
                user_states[user_id]["state"] = "modify_expiration_date"
                reply = "請輸入新的有效日期："
            else:
                reply = "請輸入有效的選項（1 或 2）。"
        elif state == "modify_name":
            ingredient_id = user_states[user_id]["data"]["id"]
            modify_ingredient(ingredient_id, name=user_message.strip())
            reply = f"已成功修改食材名稱為：{user_message.strip()}"
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "modify_expiration_date":
            ingredient_id = user_states[user_id]["data"]["id"]
            if validate_date(user_message.strip()):
                modify_ingredient(ingredient_id, expiration_date=user_message.strip())
                reply = f"已成功修改食材有效日期為：{user_message.strip()}"
            else:
                reply = "日期格式錯誤，請使用正確的格式（YYYY/MM/DD）。"
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "recipe":
            try:
                model = generativeai.GenerativeModel('gemini-2.0-flash-exp')
                response = model.generate_content(f"請用以下食材創建食譜: {user_message}")
                reply = response.text
            except Exception as e:
                reply = f"AI 發生錯誤：{str(e)}"
        else:
            reply = "無法識別指令。請試試看「新增」、「查詢」、「刪除」、「修改」、「食譜」。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# 驗證日期
def validate_date(date_text):
    try:
        datetime.strptime(date_text, '%Y/%m/%d')
        return True
    except ValueError:
        return False

# 資料庫操作功能
def get_all_ingredients():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM ingredients ORDER BY id')
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"查詢資料庫時發生錯誤：{str(e)}")
        return []

def add_ingredient(name, expiration_date):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO ingredients (name, expiration_date) VALUES (?, ?)', (name, expiration_date))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"新增食材時發生錯誤：{str(e)}")

def delete_ingredients(ids):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.executemany('DELETE FROM ingredients WHERE id = ?', [(i,) for i in ids])
        cursor.execute('UPDATE ingredients SET id = ROWID')
        conn.commit()
        conn.close()
        logging.info(f"已成功刪除食材並重新編排ID。")
    except Exception as e:
        logging.error(f"刪除食材時發生錯誤：{str(e)}")

def check_ingredient_exists(ingredient_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM ingredients WHERE id = ?', (ingredient_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        logging.error(f"檢查食材存在時發生錯誤：{str(e)}")
        return False

def modify_ingredient(ingredient_id, name=None, expiration_date=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if name:
            cursor.execute('UPDATE ingredients SET name = ? WHERE id = ?', (name, ingredient_id))
        if expiration_date:
            cursor.execute('UPDATE ingredients SET expiration_date = ? WHERE id = ?', (expiration_date, ingredient_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"修改食材時發生錯誤：{str(e)}")

if __name__ == "__main__":
    app.run(debug=False)