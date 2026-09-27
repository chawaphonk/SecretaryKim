import os
import re
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
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
    MessageAction,
    FlexMessage,
    FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from supabase import create_client, Client

app = FastAPI()

# สร้างและแมพโฟลเดอร์สำหรับเก็บไฟล์ Excel ชั่วคราว
os.makedirs("downloads", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

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
    reply_message_obj = None  # ใช้รองรับข้อความประเภทอื่นนอกจาก TextMessage

    # 1. คำสั่ง 'สรุป' เพื่อดูรายงานภาพรวม
    if user_text == "สรุป":
        response = supabase.table("transactions").select("*").eq("line_user_id", user_id).execute()
        records = response.data

        if not records:
            reply_text = "ยังไม่มีข้อมูลรายรับ-รายจ่ายบันทึกไว้ครับ"
        else:
            total_income = sum(r['amount'] for r in records if r.get('type') == 'income')
            total_expense = sum(r['amount'] for r in records if r.get('type') == 'expense')
            balance = total_income - total_expense

            category_totals = {}
            for r in records:
                if r.get('type') == 'expense':
                    cat = r.get('category') or "ไม่ระบุหมวดหมู่"
                    category_totals[cat] = category_totals.get(cat, 0.0) + r['amount']

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

    # 2. เพิ่มใหม่: คำสั่งส่งไฟล์ Excel (พิมพ์ "ดึงไฟล์", "ขอไฟล์", "excel")
    elif user_text in ["ดึงไฟล์", "ขอไฟล์", "excel", "ส่งไฟล์"]:
        try:
            response = supabase.table("transactions").select("*").eq("line_user_id", user_id).order("created_at",
                                                                                                    desc=False).execute()
            records = response.data

            if not records:
                reply_text = "ยังไม่มีข้อมูลรายรับ-รายจ่ายสำหรับส่งออกเป็นไฟล์ Excel ครับ"
            else:
                # แปลงข้อมูลเป็น DataFrame
                data_list = []
                for idx, r in enumerate(records, 1):
                    created_dt = r.get("created_at", "")
                    if created_dt:
                        dt_obj = datetime.fromisoformat(created_dt.replace("Z", "+00:00"))
                        date_str = dt_obj.strftime("%d/%m/%Y %H:%M")
                    else:
                        date_str = "-"

                    data_list.append({
                        "ลำดับ": idx,
                        "วัน-เวลา": date_str,
                        "รายการ": r.get("item", ""),
                        "ประเภท": "รายรับ" if r.get("type") == "income" else "รายจ่าย",
                        "จำนวนเงิน (บาท)": r.get("amount", 0.0),
                        "หมวดหมู่": r.get("category", "ไม่ระบุ")
                    })

                df = pd.DataFrame(data_list)

                # บันทึกเป็นไฟล์ .xlsx
                filename = f"report_{user_id}_{int(datetime.now().timestamp())}.xlsx"
                filepath = os.path.join("downloads", filename)
                df.to_excel(filepath, index=False, engine='openpyxl')

                # ลิงก์ดาวน์โหลด (แก้ไข URL ให้ถูกต้องเรียบร้อยแล้ว)
                download_url = f"https://srv-dankhjrtqb8s73c7n40g.onrender.com/downloads/{filename}"

                # สร้างปุ่ม Flex Message ให้คุณแม่กดดาวน์โหลด
                flex_json = {
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "📊 รายงานไฟล์ Excel", "weight": "bold", "size": "lg",
                             "color": "#1DB446"},
                            {"type": "text", "text": "รวบรวมข้อมูลรายรับ-รายจ่ายทั้งหมดเรียบร้อยครับ", "size": "sm",
                             "color": "#666666", "wrap": True, "margin": "md"}
                        ]
                    },
                    "footer": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "button",
                                "style": "primary",
                                "color": "#1DB446",
                                "action": {
                                    "type": "uri",
                                    "label": "🟢 ดาวน์โหลดไฟล์ Excel",
                                    "uri": download_url
                                }
                            }
                        ]
                    }
                }
                reply_message_obj = FlexMessage(alt_text="ดาวน์โหลดไฟล์ Excel",
                                                contents=FlexContainer.from_dict(flex_json))
        except Exception as e:
            print("Error generating excel:", e)
            reply_text = f"เกิดข้อผิดพลาดในการสร้างไฟล์ Excel: {e}"

    # 3. คำสั่งเพิ่มหมวดหมู่ใหม่
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

    # 4. คำสั่งลบรายการล่าสุด
    elif user_text in ["ลบรายการล่าสุด", "ลบ", "ยกเลิก"]:
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

            supabase.table("transactions").delete().eq("id", item_id).execute()

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

    # 5. กรณีเลือกหมวดหมู่รายการที่รอดำเนินการอยู่
    elif user_id in pending_transactions:
        selected_cat = user_text.replace("📁 ", "").strip()

        data = pending_transactions.pop(user_id)
        item_name = data["item"]
        amount = data["amount"]
        trans_type = data["type"]

        supabase.table("transactions").insert({
            "line_user_id": user_id,
            "item": item_name,
            "amount": amount,
            "type": trans_type,
            "category": selected_cat
        }).execute()

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

    # 6. กรณีบันทึกรายการใหม่
    else:
        match = re.match(r"^(.+)\s+(\d+(\.\d+)?)$", user_text)
        if match:
            item_name = match.group(1).strip()
            amount = float(match.group(2))
            trans_type = "income" if any(kw in item_name for kw in ["เงินเดือน", "ขาย", "ได้"]) else "expense"

            pending_transactions[user_id] = {
                "item": item_name,
                "amount": amount,
                "type": trans_type
            }

            cats_res = supabase.table("categories").select("name").eq("line_user_id", user_id).execute()
            custom_cats = [r["name"] for r in cats_res.data]
            all_categories = list(set(DEFAULT_CATEGORIES + custom_cats))

            items = [
                QuickReplyItem(
                    action=MessageAction(label=f"📁 {cat[:15]}", text=cat)
                )
                for cat in all_categories[:13]
            ]
            quick_reply_obj = QuickReply(items=items)

            type_label = "รายรับ" if trans_type == "income" else "รายจ่าย"
            reply_text = f"📌 เลือกหมวดหมู่สำหรับ [{type_label}] '{item_name}' ({amount:,.2f} บาท):"
        else:
            reply_text = (
                "โปรดพิมพ์ในรูปแบบ: [รายการ] [จำนวนเงิน]\n"
                "เช่น: ค่าอาหาร 120\n\n"
                "พิมพ์ 'ดึงไฟล์' หรือ 'ขอไฟล์' เพื่อรับไฟล์ Excel 📊\n"
                "หรือพิมพ์ 'สรุป', 'เพิ่มหมวดหมู่', 'ลบ' ได้ครับ"
            )

    # เตรียมการส่งข้อความตอบกลับ
    if not reply_message_obj:
        reply_message_obj = TextMessage(text=reply_text, quick_reply=quick_reply_obj)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[reply_message_obj]
            )
        )
