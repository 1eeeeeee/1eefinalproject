import sqlite3
from datetime import datetime, timedelta
from linebot import LineBotApi
from linebot.models import TextSendMessage
import os
import logging

# 設定環境變數
DB_PATH = os.path.join(os.getcwd(), 'data', 'ingredients.db')
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
USER_ID = os.getenv('LINE_USER_ID')  # 添加用戶ID環境變數

# 設定LOG紀錄
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_reminders():
    logging.info("send_reminders 函數已觸發")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 獲取過期或即將過期的食材（5日內過期）
        today = datetime.now()
        threshold_date = (today + timedelta(days=5)).strftime('%Y/%m/%d')
        cursor.execute('''
            SELECT name, expiration_date FROM ingredients
            WHERE expiration_date <= ?
        ''', (threshold_date,))
        rows = cursor.fetchall()
        conn.close()

        if rows:
            for row in rows:
                name, expiration_date = row
                message = f"提醒：食材 {name} 將於 {expiration_date} 過期。"
                logging.info(message)
                # 發送提醒訊息
                line_bot_api.push_message(USER_ID, TextSendMessage(text=message))
        else:
            logging.info("沒有即將過期的食材。")
    except Exception as e:
        logging.error(f"發送提醒時發生錯誤：{str(e)}")