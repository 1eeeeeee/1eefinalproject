from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import sqlite3

# 初始化 Flask 應用程式
app = Flask(__name__)

# LINE Bot API 與 Webhook Handler
LINE_CHANNEL_ACCESS_TOKEN = 'HeIvvTbdmlDKbmAztPcONNrxFxYQmfBIuEzbOuX7n2PkA2efxjgRsVoY2GqcBqb3dLFuAQ0Ztnz5lIJtMC6CtowrNlCYwND6usiL78B9ehEXABjHIYiV4w8AsLv9JoMTSMMwR5yO15dumsW01SpgOgdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '6581ae87e6194dfaa82ef23a49d23330'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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

# 新增食材
def add_ingredient(name, expiration_date):
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO ingredients (name, expiration_date)
        VALUES (?, ?)
    ''', (name, expiration_date))
    conn.commit()
    conn.close()

# 查詢食材
def get_all_ingredients():
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM ingredients')
    rows = cursor.fetchall()
    conn.close()
    return rows

# 刪除食材
def delete_ingredient(ingredient_id):
    conn = sqlite3.connect('ingredients.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM ingredients WHERE id = ?', (ingredient_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0  # 回傳是否成功刪除

# LINE Webhook 路由
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    if user_message.startswith("新增"):
        try:
            # 格式: 新增 食材名稱 YYYY-MM-DD
            _, name, expiration_date = user_message.split()
            add_ingredient(name, expiration_date)
            reply = f"已新增食材：{name}, 有效日期：{expiration_date}"
        except ValueError:
            reply = "格式錯誤！請使用「新增 食材名稱 YYYY/MM/DD」"
    elif user_message == "查詢":
        ingredients = get_all_ingredients()
        if ingredients:
            reply = "\n".join([f"{row[0]}. {row[1]} (有效日期: {row[2]})" for row in ingredients])
        else:
            reply = "目前沒有任何食材記錄。"
    elif user_message.startswith("刪除"):
        try:
            # 格式: 刪除 食材ID
            _, ingredient_id = user_message.split()
            success = delete_ingredient(int(ingredient_id))
            if success:
                reply = f"已成功刪除 ID 為 {ingredient_id} 的食材。"
            else:
                reply = f"找不到 ID 為 {ingredient_id} 的食材，請確認後再試。"
        except ValueError:
            reply = "格式錯誤！請使用「刪除 食材ID」"
    else:
        reply = "請輸入「新增 食材名稱 YYYY/MM/DD」、「查詢」或「刪除 食材ID」來管理食材。"

    # 回覆訊息
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# 主程式
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
