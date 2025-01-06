import os
import sqlite3
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as generativeai
import schedule
import time
import threading
from reminder import send_reminders  # 確保這個函數存在於你的 reminder.py 文件中

# 載入環境變數
load_dotenv()

# 設置 Google Generative AI API 密鑰
generativeai.configure(api_key=os.getenv('KEY'))

# 初始化 Flask 應用和 LINE API
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 用戶狀態管理
user_states = {}

# 資料庫文件路徑
DB_PATH = os.path.join(os.getcwd(), 'data', 'ingredients.db')

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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY
            )
        ''')
        conn.commit()
        conn.close()
        logging.info(f"已成功重新生成資料庫，路徑：{DB_PATH}")
    except Exception as e:
        logging.error(f"資料庫初始化時發生錯誤：{str(e)}")
init_db()

# 手動新增即將過期的食材
def add_test_ingredients():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # 新增一個即將過期的食材
        expiration_date = (datetime.now() + timedelta(days=3)).strftime('%Y/%m/%d')
        cursor.execute('INSERT INTO ingredients (name, expiration_date) VALUES (?, ?)', ('測試食材', expiration_date))
        conn.commit()
        conn.close()
        logging.info("已成功新增測試食材")
    except Exception as e:
        logging.error(f"新增測試食材時發生錯誤：{str(e)}")

add_test_ingredients()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    logging.info(f"收到來自LINE的Webhook請求：{body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("Invalid signature. Check your channel access token/channel secret.")
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id  # 獲取用戶 ID
    logging.info(f"收到來自用戶 {user_id} 的訊息")
    user_message = event.message.text.strip()

    # 將用戶 ID 存儲到資料庫中
    store_user_id(user_id)

    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}

    # 處理不同的用戶命令
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
        reply = "請輸入要刪除的食材ID："
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
            successes = []
            for ingredient in ingredients:
                try:
                    parts = ingredient.split()
                    if len(parts) != 2:
                        errors.append(f"格式錯誤：{ingredient}")
                        continue
                    name, expiration_date = parts
                    if validate_date(expiration_date.strip()):
                        add_ingredient(name.strip(), expiration_date.strip())
                        successes.append(f"{name.strip()} {expiration_date.strip()}")
                    else:
                        errors.append(f"日期無效或過去日期：{expiration_date.strip()}")
                except ValueError:
                    errors.append(f"格式錯誤：{ingredient}")
            reply = ""
            if successes:
                reply += "已成功新增：\n" + "\n".join(successes)
            if errors:
                reply += "以下食材新增失敗：\n" + "\n".join(errors)
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "delete":
            try:
                ingredient_id = int(user_message.strip())
                delete_ingredient(ingredient_id)
                reply = f"已成功刪除食材，ID：{ingredient_id}"
            except ValueError:
                reply = "格式錯誤，請輸入正確的食材ID。"
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "modify_select_id":
            try:
                ingredient_id = int(user_message.strip())
                user_states[user_id] = {"state": "modify_select_field", "data": {"id": ingredient_id}}
                reply = "請選擇要修改的欄位：\n1. 名稱\n2. 有效日期"
            except ValueError:
                reply = "格式錯誤，請輸入正確的食材ID。"
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
            modify_ingredient(ingredient_id, new_name=user_message.strip())
            reply = f"已成功修改食材名稱為：{user_message.strip()}"
            user_states[user_id] = {"state": None, "data": {}}
        elif state == "modify_expiration_date":
            ingredient_id = user_states[user_id]["data"]["id"]
            if validate_date(user_message.strip()):
                modify_ingredient(ingredient_id, new_expiration_date=user_message.strip())
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

def store_user_id(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"存儲用戶ID時發生錯誤：{str(e)}")

# 資料庫操作的輔助函數
def validate_date(date_text):
    try:
        input_date = datetime.strptime(date_text, '%Y/%m/%d')
        if input_date < datetime.now():
            return False  
        return True
    except ValueError:
        return False

def get_all_ingredients():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, expiration_date FROM ingredients ORDER BY id')
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

def delete_ingredient(ingredient_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ingredients WHERE id = ?', (ingredient_id,))
        conn.commit()

        # 重新排列所有食材的 ID
        cursor.execute('SELECT id FROM ingredients ORDER BY id')
        rows = cursor.fetchall()
        for new_id, (old_id,) in enumerate(rows, start=1):
            cursor.execute('UPDATE ingredients SET id = ? WHERE id = ?', (new_id, old_id))
        conn.commit()
        conn.close()
        logging.info(f"已成功刪除食材，ID：{ingredient_id}")
    except Exception as e:
        logging.error(f"刪除食材時發生錯誤：{str(e)}")

def modify_ingredient(ingredient_id, new_name=None, new_expiration_date=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if new_name:
            cursor.execute('UPDATE ingredients SET name = ? WHERE id = ?', (new_name, ingredient_id))
        if new_expiration_date:
            cursor.execute('UPDATE ingredients SET expiration_date = ? WHERE id = ?', (new_expiration_date, ingredient_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"修改食材時發生錯誤：{str(e)}")

# 排程提醒
def schedule_reminders():
    # 設定每天指定時間執行提醒任務
    now = datetime.now()
    target_time = datetime.combine(now.date(), datetime.strptime("16:03", "%H:%M").time())
    if now > target_time:
        target_time += timedelta(days=1) 
    delay = (target_time - now).total_seconds()

    # 使用 Timer 設置延遲執行
    threading.Timer(delay, send_reminders).start()
    logging.info(f"提醒排程已設定，將於 {target_time.strftime('%Y-%m-%d %H:%M')} 執行")

def run_schedule():
    while True:
        schedule.run_pending()
        logging.debug("正在檢查排程任務")  # 修改為 DEBUG 級別
        time.sleep(600)

# 運行 Flask 應用
if __name__ == "__main__":
    schedule_reminders()
    schedule_thread = threading.Thread(target=run_schedule)
    schedule_thread.start()
    app.run(debug=False)