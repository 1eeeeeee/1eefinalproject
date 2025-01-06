import logging
from linebot import LineBotApi
from linebot.models import TextSendMessage
import os
import sqlite3
from datetime import datetime, timedelta

# 初始化 LINE API
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

def send_reminders():
    try:
        # 連接到資料庫
        conn = sqlite3.connect('data/ingredients.db')
        cursor = conn.cursor()

        # 獲取即將過期的食材
        expiration_date_limit = (datetime.now() + timedelta(days=3)).strftime('%Y/%m/%d')
        cursor.execute('SELECT name, expiration_date FROM ingredients WHERE expiration_date <= ?', (expiration_date_limit,))
        rows = cursor.fetchall()

        # 獲取所有用戶 ID
        cursor.execute('SELECT user_id FROM users')
        user_ids = cursor.fetchall()
        conn.close()

        if rows:
            for row in rows:
                message = f"提醒：{row[0]} 即將於 {row[1]} 過期！"
                for user_id in user_ids:
                    line_bot_api.push_message(user_id[0], TextSendMessage(text=message))
                    logging.info(f"已發送提醒給用戶 {user_id[0]}：{message}")
        else:
            logging.info("沒有即將過期的食材。")
    except Exception as e:
        logging.error(f"發送提醒時發生錯誤：{str(e)}")