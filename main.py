import os
import re
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from supabase import create_client, Client

app = FastAPI()

# Keys
LINE_CHANNEL_ACCESS_TOKEN = "EOJmyUuFqtRB4XXcmr3n1uClgWVyQEgMDZxhr73mvds0s5M/gaRKjHeY73nO2dq8ZsC7po/RTXfutG8B1R21ziC+ZHndfItC999MTmSqzWo1qBMf5rRll6nYFr6MCUddwDTQCBhvhEfeAA/nvo4T+gdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "8bb577ddf6791e5981675e12a41be05c"
SUPABASE_URL = "https://hprdhjjqskkvmzfdxiyw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhwcmRoampxc2trdm16ZmR4aXl3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk2OTc5OTQsImV4cCI6MjEwNTI3Mzk5NH0.eQ4c1-WsunjwIl9DslPher5YJlIMe2dt791Dhcc5_0M"

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id

    # 1. กรณีผู้ใช้พิมพ์คำว่า "สรุป" เพื่อดูรายงานแบบละเอียด
    if user_text == "สรุป":
        response = supabase.table("transactions").select("*").eq("line_user_id", user_id).execute()
        records = response.data

        if not records:
            reply_text = "ยังไม่มีข้อมูลรายรับ-รายจ่ายบันทึกไว้ครับ"
        else:
            total_income = sum(r['amount'] for r in records if r['type'] == 'income')
            total_expense = sum(r['amount'] for r in records if r['type'] == 'expense')
            balance = total_income - total_expense

            reply_text = (
                f"📊 **สรุปยอดรวมทั้งหมด**\n\n"
                f"📈 รายรับรวม: {total_income:,.2f} บาท\n"
                f"📉 รายจ่ายรวม: {total_expense:,.2f} บาท\n"
                f"➖➖➖➖➖➖➖➖➖\n"
                f"💰 ยอดคงเหลือ: {balance:,.2f} บาท"
            )

    # 2. กรณีบันทึกรายการรายรับ-รายจ่าย
    else:
        match = re.match(r"^(.+)\s+(\d+(\.\d+)?)$", user_text)
        if match:
            item_name = match.group(1).strip()
            amount = float(match.group(2))

            # แยกประเภท รายรับ / รายจ่าย
            trans_type = "income" if any(kw in item_name for kw in ["เงินเดือน", "ขาย", "ได้"]) else "expense"

            data = {
                "line_user_id": user_id,
                "item": item_name,
                "amount": amount,
                "type": trans_type
            }

            # บันทึกลง Supabase
            supabase.table("transactions").insert(data).execute()

            # --- ดึงข้อมูลทั้งหมดมาคำนวณยอดรวมล่าสุดทันที ---
            response = supabase.table("transactions").select("*").eq("line_user_id", user_id).execute()
            records = response.data

            total_income = sum(r['amount'] for r in records if r['type'] == 'income')
            total_expense = sum(r['amount'] for r in records if r['type'] == 'expense')
            balance = total_income - total_expense

            type_label = "รายรับ 📈" if trans_type == "income" else "รายจ่าย 📉"
            reply_text = (
                f"บันทึกสำเร็จ! ✅\n"
                f"{type_label}: {item_name} ({amount:,.2f} บาท)\n"
                f"➖➖➖➖➖➖➖➖➖\n"
                f"💰 ยอดคงเหลือล่าสุด: {balance:,.2f} บาท"
            )
        else:
            reply_text = "โปรดพิมพ์ในรูปแบบ: [รายการ] [จำนวนเงิน]\nเช่น: ค่าอาหาร 120\nหรือพิมพ์ 'สรุป' เพื่อดูรายงานยอดรวม"

    # ส่งข้อความตอบกลับไปยัง LINE
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
