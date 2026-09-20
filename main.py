import re
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from supabase import create_client, Client

app = FastAPI()

# Keys
LINE_CHANNEL_ACCESS_TOKEN = "EOJmyUuFqtRB4XXcmr3n1uClgWVyQEgMDZxhr73mvds0s5M/gaRKjHeY73nO2dq8ZsC7po/RTXfutG8B1R21ziC+ZHndfItC999MTmSqzWo1qBMf5rRll6nYFr6MCUddwDTQCBhvhEfeAA/nvo4T+gdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "8bb577ddf6791e5981675e12a41be05c"
SUPABASE_URL = "https://hprdhjjqskkvmzfdxiyw.supabase.co/rest/v1/"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhwcmRoampxc2trdm16ZmR4aXl3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk2OTc5OTQsImV4cCI6MjEwNTI3Mzk5NH0.eQ4c1-WsunjwIl9DslPher5YJlIMe2dt791Dhcc5_0M"

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.get("/")
def home():
    return {"status": "Bot is running!"}


@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    match = re.match(r"^(.+)\s+(\d+(\.\d+)?)$", text)

    if match:
        category = match.group(1).strip()
        amount = float(match.group(2))

        data = {
            "line_user_id": user_id,
            "type": "expense",
            "category": category,
            "amount": amount
        }
        supabase.table("transactions").insert(data).execute()
        reply_text = f"บันทึกสำเร็จ!\nรายการ: {category}\nจำนวน: {amount:,.2f} บาท"
    else:
        reply_text = "กรุณาพิมพ์ในรูปแบบ: [ชื่อรายการ] [จำนวนเงิน]\nตัวอย่าง: ค่าอาหาร 120"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )