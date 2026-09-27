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
    TextMessage,
    QuickReply,
    QuickReplyItem,
    MessageAction
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

# หน่วยความจำชั่วคราวสำหรับพักรายการรอเลือกหมวดหมู่
pending_transactions = {}

# หมวดหมู่เริ่มต้นระบบ
DEFAULT_CATEGORIES = ["อาหาร", "เดินทาง", "บ้าน/ครอบครัว", "ช้อปปิ้ง", "ค่าน้ำค่าน้ำไฟ", "อื่นๆ"]


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
    quick_reply_obj = None

    # 1. คำสั่ง 'สรุป' เพื่อดูรายงานภาพรวม และแยกตามหมวดหมู่
    if user_text == "สรุป":
        response = supabase.table("transactions").select("*").eq("line_user_id", user_id).execute()
        records = response.data

        if not records:
            reply_text = "ยังไม่มีข้อมูลรายรับ-รายจ่ายบันทึกไว้ครับ"
        else:
            total_income = sum(r['amount'] for r in records if r.get('type') == 'income')
            total_expense = sum(r['amount'] for r in records if r.get('type') == 'expense')
            balance = total_income - total_expense

            # จัดกลุ่มคำนวณยอดรวมแยกตามหมวดหมู่ (เฉพาะรายจ่าย)
            category_totals = {}
            for r in records:
                if r.get('type') == 'expense':
                    cat = r.get('category') or "ไม่ระบุหมวดหมู่"
                    category_totals[cat] = category_totals.get(cat, 0.0) + r['amount']

            # สร้างข้อความสรุปแยกหมวดหมู่
            cat_summary_text = ""
            if category_totals:
                cat_summary_text = "\n\n📌 **ยอดรายจ่ายแยกตามหมวดหมู่:**\n"
                for cat, amt in category_totals.items():
                    cat_summary_text += f"• {cat}: {amt:,.2f} บาท\n"

            reply_text = (
                f"📊 **สรุปยอดรวมทั้งหมด**\n\n"
                f"📈 รายรับรวม: {total_income:,.2f} บาท\n"
                f"📉 รายจ่ายรวม: {total_expense:,.2f} บาท\n"
                f"➖➖➖➖➖➖➖➖➖\n"
                f"💰 ยอดคงเหลือ: {balance:,.2f} บาท"
                f"{cat_summary_text}"
            )

    # 2. คำสั่งเพิ่มหมวดหมู่ใหม่ (เช่น: เพิ่มหมวดหมู่ เสริมสวย)
    elif user_text.startswith("เพิ่มหมวดหมู่"):
        new_cat = user_text.replace("เพิ่มหมวดหมู่", "").strip()
        if not new_cat:
            reply_text = "โปรดระบุชื่อหมวดหมู่ด้วยครับ เช่น:\nเพิ่มหมวดหมู่ เสริมสวย"
        else:
            supabase.table("categories").insert({
                "line_user_id": user_id,
                "name": new_cat
            }).execute()
            reply_text = f"เพิ่มหมวดหมู่ '{new_cat}' เรียบร้อยแล้วครับ! ✨"

    # 3. เพิ่มใหม่: คำสั่งลบรายการล่าสุด (รองรับคำว่า "ลบรายการล่าสุด", "ลบ", "ยกเลิก")
    elif user_text in ["ลบรายการล่าสุด", "ลบ", "ยกเลิก"]:
        # ดึงรายการล่าสุดของผู้ใช้โดยเรียงตามเวลาที่บันทึก (created_at)
        res = supabase.table("transactions") \
            .select("*") \
            .eq("line_user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if res.data:
            latest_item = res.data[0]
            item_id = latest_item["id"]
            item_name = latest_item["item"]
            amount = latest_item["amount"]

            # ลบรายการล่าสุดนั้นออกจาก Supabase
            supabase.table("transactions").delete().eq("id", item_id).execute()

            # คำนวณยอดคงเหลือใหม่หลังลบ
            rem_res = supabase.table("transactions").select("*").eq("line_user_id", user_id).execute()
            records = rem_res.data
            total_income = sum(r['amount'] for r in records if r.get('type') == 'income')
            total_expense = sum(r['amount'] for r in records if r.get('type') == 'expense')
            balance = total_income - total_expense

            reply_text = (
                f"🗑️ ลบรายการล่าสุดเรียบร้อยแล้ว!\n"
                f"รายการที่ลบ: {item_name} ({amount:,.2f} บาท)\n"
                f"➖➖➖➖➖➖➖➖➖\n"
                f"💰 ยอดคงเหลือปัจจุบัน: {balance:,.2f} บาท"
            )
        else:
            reply_text = "ยังไม่มีรายการบันทึกให้ลบครับ"

    # 4. กรณีผู้ใช้กดเลือกหมวดหมู่รายการที่รอดำเนินการอยู่
    elif user_id in pending_transactions:
        selected_cat = user_text.replace("📁 ", "").strip()

        # ดึงข้อมูลรายการที่พักไว้
        data = pending_transactions.pop(user_id)
        item_name = data["item"]
        amount = data["amount"]
        trans_type = data["type"]

        # บันทึกลง Supabase พร้อมหมวดหมู่
        supabase.table("transactions").insert({
            "line_user_id": user_id,
            "item": item_name,
            "amount": amount,
            "type": trans_type,
            "category": selected_cat
        }).execute()

        # คำนวณยอดคงเหลือล่าสุด
        response = supabase.table("transactions").select("*").eq("line_user_id", user_id).execute()
        records = response.data
        total_income = sum(r['amount'] for r in records if r.get('type') == 'income')
        total_expense = sum(r['amount'] for r in records if r.get('type') == 'expense')
        balance = total_income - total_expense

        type_label = "รายรับ 📈" if trans_type == "income" else "รายจ่าย 📉"
        reply_text = (
            f"บันทึกสำเร็จ! ✅\n"
            f"{type_label}: {item_name} ({amount:,.2f} บาท)\n"
            f"📁 หมวดหมู่: {selected_cat}\n"
            f"➖➖➖➖➖➖➖➖➖\n"
            f"💰 ยอดคงเหลือล่าสุด: {balance:,.2f} บาท"
        )

    # 5. กรณีบันทึกรายการใหม่ (เช่น: ค่าทำผม 500)
    else:
        match = re.match(r"^(.+)\s+(\d+(\.\d+)?)$", user_text)
        if match:
            item_name = match.group(1).strip()
            amount = float(match.group(2))
            trans_type = "income" if any(kw in item_name for kw in ["เงินเดือน", "ขาย", "ได้"]) else "expense"

            # พักข้อมูลรายการไว้
            pending_transactions[user_id] = {
                "item": item_name,
                "amount": amount,
                "type": trans_type
            }

            # ดึงหมวดหมู่ของผู้ใช้จาก Supabase
            cats_res = supabase.table("categories").select("name").eq("line_user_id", user_id).execute()
            custom_cats = [r["name"] for r in cats_res.data]
            all_categories = list(set(DEFAULT_CATEGORIES + custom_cats))

            # สร้างปุ่ม Quick Reply ในรูปแบบ SDK v3
            items = [
                QuickReplyItem(
                    action=MessageAction(label=f"📁 {cat[:15]}", text=cat)
                )
                for cat in all_categories[:13]  # LINE รองรับสูงสุด 13 ปุ่ม
            ]
            quick_reply_obj = QuickReply(items=items)

            type_label = "รายรับ" if trans_type == "income" else "รายจ่าย"
            reply_text = f"📌 เลือกหมวดหมู่สำหรับ [{type_label}] '{item_name}' ({amount:,.2f} บาท):"
        else:
            reply_text = (
                "โปรดพิมพ์ในรูปแบบ: [รายการ] [จำนวนเงิน]\n"
                "เช่น: ค่าอาหาร 120\n\n"
                "หรือพิมพ์เพิ่มหมวดหมู่ใหม่ เช่น:\nเพิ่มหมวดหมู่ เสริมสวย\n\n"
                "หากบันทึกผิด พิมพ์คำว่า 'ลบ' หรือ 'ลบรายการล่าสุด' ได้ครับ"
            )


    # ส่งข้อความตอบกลับไปยัง LINE
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=reply_text,
                        quick_reply=quick_reply_obj
                    )
                ]
            )
        )
