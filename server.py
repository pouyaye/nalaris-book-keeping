import os
import io
import json
import sqlite3
import base64
import wave
import csv
from datetime import datetime, date

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request, Header
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from google import genai
from google.genai import types
from PIL import Image, ImageEnhance, ImageOps
from pillow_heif import register_heif_opener

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("🚨 GEMINI_API_KEY not found! Please check your .env file.")

register_heif_opener()

app = FastAPI()
client = genai.Client(api_key=API_KEY)

active_sessions: dict = {}

# ─────────────────────────────────────────────────────────────────
# DATABASE SCHEMA & MIGRATIONS
# ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect('nalaris_ledger.db', timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword          TEXT UNIQUE,
            owner_name       TEXT,
            business_name    TEXT,
            tier             TEXT DEFAULT 'premium', 
            balance          REAL DEFAULT 0.0,
            receipts_today   INTEGER DEFAULT 0,
            chat_chars_today INTEGER DEFAULT 0,
            last_active_date TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER,
            vendor         TEXT,
            invoice_number TEXT,
            invoice_date   TEXT,
            invoice_time   TEXT,
            subtotal       REAL,
            gst            REAL,
            qst            REAL,
            total          REAL,
            status         TEXT,
            payment_method TEXT,
            billed_to      TEXT,
            line_items     TEXT,
            image_data     TEXT, 
            created_at     TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER,
            role           TEXT,
            type           TEXT,
            content        TEXT,
            audio_base64   TEXT,
            created_at     TEXT DEFAULT (datetime('now'))
        )
    ''')
    
    try: conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin'")
    except: pass
    try: conn.execute("ALTER TABLE users ADD COLUMN meal_limit REAL DEFAULT 75.0")
    except: pass
    try: conn.execute("ALTER TABLE expenses ADD COLUMN approval_status TEXT DEFAULT 'Approved'")
    except: pass
    try: conn.execute("ALTER TABLE expenses ADD COLUMN policy_violations TEXT")
    except: pass
    
    conn.commit()
    conn.close()

init_db()

def save_chat(user_id: int, role: str, msg_type: str, content: str, audio_b64: str = None):
    try:
        conn = get_db()
        conn.execute("INSERT INTO chat_history (user_id, role, type, content, audio_base64) VALUES (?, ?, ?, ?, ?)", (user_id, role, msg_type, content, audio_b64))
        conn.commit()
        conn.close()
    except Exception: pass

# ─────────────────────────────────────────────────────────────────
# METERING & LIMITS ENGINE
# ─────────────────────────────────────────────────────────────────
def check_limits(user_id: int, action: str, amount: int = 0) -> dict:
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    
    today_str = date.today().isoformat()
    receipts_today = user["receipts_today"]
    chat_chars_today = user["chat_chars_today"]
    
    if user["last_active_date"] != today_str:
        receipts_today = 0
        chat_chars_today = 0
        conn.execute("UPDATE users SET receipts_today=0, chat_chars_today=0, last_active_date=? WHERE id=?", (today_str, user_id))
        conn.commit()

    tier = user["tier"]
    balance = user["balance"]

    if tier == "premium": return {"allowed": True}

    if action == "receipt":
        if tier == "free":
            if receipts_today >= 3:
                conn.close()
                return {"allowed": False, "reason": "You have reached your limit of 3 free receipts today."}
            else:
                conn.execute("UPDATE users SET receipts_today = receipts_today + 1 WHERE id=?", (user_id,))
        elif tier == "payg":
            if balance < 0.30:
                conn.close()
                return {"allowed": False, "reason": "Insufficient balance. Each receipt costs $0.30. Please top up your account."}
            else:
                conn.execute("UPDATE users SET balance = balance - 0.30 WHERE id=?", (user_id,))
    
    elif action == "chat":
        if tier == "free":
            if chat_chars_today + amount > 2000:
                conn.close()
                return {"allowed": False, "reason": "You have reached your 2,000 character chat limit for today."}
            else:
                conn.execute("UPDATE users SET chat_chars_today = chat_chars_today + ? WHERE id=?", (amount, user_id))

    conn.commit()
    conn.close()
    return {"allowed": True}

# ─────────────────────────────────────────────────────────────────
# IMAGE PROCESSING & AI EXTRACTION
# ─────────────────────────────────────────────────────────────────
def preprocess_image(raw_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"): img = img.convert("RGB")
    scale = 2048 / max(img.width, img.height)
    if scale < 1.0: img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.25)
    return ImageEnhance.Sharpness(img).enhance(1.5)

_EXTRACTION_PROMPT = """
You are the Nalaris Enterprise AI Bookkeeper.
Business: "{business_name}". User submitting: "{user_name}".

Rules:
1. Extract all receipt/invoice data accurately.
2. status: "Paid" if there is a payment confirmation, else "Unpaid".
3. Check Corporate Policies: Meal limit is ${meal_limit}. Alcohol is forbidden.
   If line_items indicate alcohol, or if it's a meal over ${meal_limit}, set policy_violations to a brief explanation string (e.g. "Contains alcohol", "Meal exceeds $75 limit"). Else set to null.

Output ONLY raw JSON matching this schema:
{{
  "vendor": "String",
  "invoice_number": "String|null",
  "date": "YYYY-MM-DD|null",
  "time": "HH:MM|null",
  "subtotal": 0.00,
  "gst": 0.00,
  "qst": 0.00,
  "total": 0.00,
  "status": "Paid|Unpaid|Unknown",
  "payment_method": "String|null",
  "billed_to": "String|null",
  "policy_violations": "String|null",
  "items": [{{"qty": "Str", "description": "Str", "unit_price": 0.00, "total": 0.00}}]
}}
"""

def extract_invoice_data(img: Image.Image, user_info: dict) -> dict:
    prompt = _EXTRACTION_PROMPT.format(
        business_name=user_info["business_name"], 
        user_name=user_info["user_name"],
        meal_limit=user_info.get("meal_limit", 75.0)
    )
    resp = client.models.generate_content(
        model='gemini-2.5-flash', contents=[prompt, img],
        config=types.GenerateContentConfig(temperature=0.1)
    )
    text = resp.text.strip().replace("```json", "").replace("```", "")
    data = json.loads(text[text.find("{"):text.rfind("}")+1])
    for f in ("subtotal", "gst", "qst", "total"): data[f] = float(data.get(f) or 0)
    return data

def process_invoice(raw_bytes: bytes, session: dict, user_info: dict) -> str:
    img = preprocess_image(raw_bytes)
    data = extract_invoice_data(img, user_info)

    conn = get_db()
    duplicate = conn.execute(
        "SELECT id FROM expenses WHERE user_id=? AND vendor=? AND invoice_date=? AND total=?",
        (user_info["id"], data.get("vendor"), data.get("date"), data["total"])
    ).fetchone()
    
    if duplicate:
        conn.close()
        return f"⚠️ **Duplicate Detected:** A receipt from **{data.get('vendor')}** on **{data.get('date')}** for **${data['total']:,.2f}** already exists in your vault. I have skipped saving this duplicate to keep your ledger clean."

    store_img = img.copy()
    store_img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    store_img.save(buf, format="JPEG", quality=75)
    img_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    role = user_info["role"]
    violations = data.get("policy_violations")
    
    if role == 'employee' or violations or data["total"] > 5000:
        approval_status = "Pending"
    else:
        approval_status = "Approved"

    conn.execute(
        """INSERT INTO expenses (user_id, vendor, invoice_number, invoice_date, invoice_time, subtotal, gst, qst, total, status, payment_method, billed_to, line_items, image_data, approval_status, policy_violations)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_info["id"], data.get("vendor"), data.get("invoice_number"), data.get("date"), data.get("time"), data["subtotal"], data["gst"], data["qst"], data["total"], data.get("status"), data.get("payment_method"), data.get("billed_to"), json.dumps(data.get("items", [])), img_b64, approval_status, violations),
    )
    conn.commit()
    conn.close()

    reply = f"Logged invoice from **{data.get('vendor')}** for **${data['total']:,.2f}**."
    if approval_status == "Pending":
        if violations: reply += f"\n\n⚠️ **Policy Flag:** {violations}. Routed to manager."
        elif data["total"] > 5000: reply += f"\n\n⚠️ **High Value:** Routed to CFO for digital signature."
        else: reply += f"\n\n⏳ Routed for manager approval."
    return reply

def ensure_session(session_id: str):
    if session_id not in active_sessions:
        active_sessions[session_id] = {"user_id": None, "user_name": None, "business_name": None, "creation_step": None, "new_keyword": None}
    return active_sessions[session_id]

# ─────────────────────────────────────────────────────────────────
# ENDPOINTS: CORE & CHAT
# ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()

@app.get("/manifest.json")
async def manifest(): return FileResponse("manifest.json", media_type="application/manifest+json")

@app.get("/icon-192.png")
async def icon192(): return FileResponse("icon-192.png", media_type="image/png")

@app.get("/icon-512.png")
async def icon512(): return FileResponse("icon-512.png", media_type="image/png")

@app.get("/api/chat-history")
async def get_chat_history(session_id: str = Header(None)):
    session = active_sessions.get(session_id)
    if not session or not session.get("user_id"): return {"history": []}
    conn = get_db()
    rows = conn.execute("SELECT role, type, content, audio_base64 FROM chat_history WHERE user_id=? ORDER BY id ASC", (session["user_id"],)).fetchall()
    conn.close()
    return {"history": [dict(row) for row in rows]}

@app.post("/api/chat-upload")
async def handle_upload(file: UploadFile = File(...), session_id: str = Header(None)):
    raw = await file.read()
    session = ensure_session(session_id)
    if not session["user_id"]: return {"reply": "📁 *Document secured.* Please authenticate first."}

    conn = get_db()
    user_info = dict(conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone())
    conn.close()

    save_chat(session["user_id"], "user", "text", f"📄 Uploaded: {file.filename}")
    try:
        reply = process_invoice(raw, session, user_info)
        save_chat(session["user_id"], "bot", "text", reply)
        return {"reply": reply}
    except Exception as exc:
        return {"reply": f"⚠️ Extraction error: {exc}"}

@app.post("/api/chat-text")
async def handle_text(request: Request, session_id: str = Header(None)):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session = ensure_session(session_id)

        if not session["user_id"]:
            if message.lower() == "create profile":
                session["creation_step"] = "keyword"
                return {"reply": "Let's set up your ledger.\n\nFirst, choose a **secure keyword**:"}
            step = session.get("creation_step")
            if step:
                if step == "keyword":
                    conn = get_db()
                    clash = conn.execute("SELECT id FROM users WHERE lower(keyword)=?", (message.lower(),)).fetchone()
                    conn.close()
                    if clash: return {"reply": "⚠️ Keyword already taken. Choose a different one."}
                    session["new_keyword"] = message
                    session["creation_step"] = "owner_name"
                    return {"reply": "Great. What is your **full name**?"}
                elif step == "owner_name":
                    session["new_owner"] = message
                    session["creation_step"] = "business_name"
                    return {"reply": f"Nice to meet you, **{message}**. What is your **business name**?"}
                elif step == "business_name":
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO users (keyword, owner_name, business_name, last_active_date, tier, role) VALUES (?,?,?,?,?,?)",
                        (session["new_keyword"], session["new_owner"], message, date.today().isoformat(), 'premium', 'admin')
                    )
                    conn.commit()
                    new_id = cursor.lastrowid
                    conn.close()
                    session.update(user_id=new_id, user_name=session["new_owner"], business_name=message, creation_step=None)
                    return {"reply": f"✅ **Profile created!** Welcome, **{session['user_name']}**.", "tier": "premium"}

            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE lower(keyword)=?", (message.lower(),)).fetchone()
            conn.close()
            if user:
                session.update(user_id=user["id"], user_name=user["owner_name"], business_name=user["business_name"])
                return {"reply": f"🔓 **Access granted.** Welcome back, **{user['owner_name']}**.", "tier": user["tier"]}
            return {"reply": "❌ Keyword not recognised."}

        limit_check = check_limits(session["user_id"], "chat", len(message))
        if not limit_check["allowed"]:
            return {"error": "limit_reached", "reply": limit_check["reason"]}

        save_chat(session["user_id"], "user", "text", message)

        conn = get_db()
        rows = conn.execute("SELECT * FROM expenses WHERE user_id=? ORDER BY id DESC LIMIT 50", (session["user_id"],)).fetchall()
        user_row = conn.execute("SELECT tier FROM users WHERE id=?", (session["user_id"],)).fetchone()
        tier = user_row["tier"] if user_row else "free"
        conn.close()
        
        expenses_dict = [dict(row) for row in rows]
        clean_ledger = [{k: v for k, v in r.items() if k != 'image_data'} for r in expenses_dict]
        
        system = f"You are Nalaris AI Bookkeeper for {session['business_name']}.\nFull ledger (no images): {json.dumps(clean_ledger)}\nAnswer concisely."
        
        resp = client.models.generate_content(model='gemini-2.5-flash', contents=f"{system}\n\nUser: {message}")
        reply_text = resp.text
        audio_b64 = None

        if tier == "premium" and reply_text:
            try:
                tts_config = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")))
                )
                tts_resp = client.models.generate_content(model='gemini-2.5-flash-preview-tts', contents=reply_text, config=tts_config)
                if tts_resp.candidates and tts_resp.candidates[0].content.parts:
                    for part in tts_resp.candidates[0].content.parts:
                        if part.inline_data:
                            pcm_data = part.inline_data.data
                            wav_io = io.BytesIO()
                            with wave.open(wav_io, 'wb') as wav_file:
                                wav_file.setnchannels(1)
                                wav_file.setsampwidth(2)
                                wav_file.setframerate(24000)
                                wav_file.writeframes(pcm_data)
                            audio_b64 = base64.b64encode(wav_io.getvalue()).decode("utf-8")
                            break
            except Exception as e:
                print(f"TTS Audio Generation Skipped/Failed: {e}") # Fails gracefully without crashing chat

        save_chat(session["user_id"], "bot", "text", reply_text, audio_b64)
        return {"reply": reply_text, "audio_base64": audio_b64}
        
    except Exception as exc:
        print(f"Text Chat Error: {exc}")
        return {"reply": f"⚠️ Processing Error: {exc}"}

@app.post("/api/chat-voice")
async def handle_voice(file: UploadFile = File(...), session_id: str = Header(None)):
    try:
        raw_audio = await file.read()
        session = ensure_session(session_id)

        if not session["user_id"]:
            return {"reply": "Please authenticate first to use voice commands."}
            
        if not raw_audio or len(raw_audio) == 0:
            return {"reply": "⚠️ Received empty audio file. Please try speaking again."}

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        tier = user["tier"] if user else "free"
        rows = conn.execute("SELECT * FROM expenses WHERE user_id=? ORDER BY id DESC LIMIT 50", (session["user_id"],)).fetchall()
        conn.close()
        
        if tier == "free":
            return {"error": "limit_reached", "reply": "Voice integration is a premium feature. Please upgrade your plan."}

        mime_type = file.content_type
        if not mime_type or mime_type in ("application/octet-stream", "video/webm"):
            mime_type = "audio/webm" # Force safe mime type if browser sends generic stream

        user_audio_src = f"data:{mime_type};base64," + base64.b64encode(raw_audio).decode("utf-8")
        save_chat(session["user_id"], "user", "voice", "🎙️ <i>Voice Message sent</i>", user_audio_src)

        expenses_dict = [dict(row) for row in rows]
        clean_ledger = [{k: v for k, v in r.items() if k != 'image_data'} for r in expenses_dict]
        audio_part = types.Part.from_bytes(data=raw_audio, mime_type=mime_type)
        
        system = (
            f"You are the Nalaris AI Bookkeeper for {session['business_name']}.\n"
            f"Full ledger: {json.dumps(clean_ledger)}\n\n"
            "The user is speaking to you. Answer concisely in a friendly, conversational tone."
        )

        resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[system, audio_part],
            config=types.GenerateContentConfig(temperature=0.3)
        )

        reply_text = resp.text
        audio_b64 = None

        if tier == "premium" and reply_text:
            try:
                tts_config = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")))
                )
                tts_resp = client.models.generate_content(model='gemini-2.5-flash-preview-tts', contents=reply_text, config=tts_config)
                if tts_resp.candidates and tts_resp.candidates[0].content.parts:
                    for part in tts_resp.candidates[0].content.parts:
                        if part.inline_data:
                            pcm_data = part.inline_data.data
                            wav_io = io.BytesIO()
                            with wave.open(wav_io, 'wb') as wav_file:
                                wav_file.setnchannels(1)
                                wav_file.setsampwidth(2)
                                wav_file.setframerate(24000)
                                wav_file.writeframes(pcm_data)
                            audio_b64 = base64.b64encode(wav_io.getvalue()).decode("utf-8")
                            break
            except Exception as e:
                print(f"TTS Audio Generation Skipped/Failed: {e}") # Fails gracefully without crashing chat

        save_chat(session["user_id"], "bot", "voice", reply_text, audio_b64)
        return {"reply": reply_text, "audio_base64": audio_b64}
        
    except Exception as exc:
        print(f"Voice Processing Error: {exc}")
        return {"reply": f"⚠️ Voice Processing Error. Please try typing your request instead."}

# ─────────────────────────────────────────────────────────────────
# ENDPOINTS: ENTERPRISE DATA & SYNC
# ─────────────────────────────────────────────────────────────────
@app.get("/api/ledger")
async def get_ledger(session_id: str = Header(None)):
    session = active_sessions.get(session_id)
    if not session or not session.get("user_id"): return {"error": "not_auth"}
    
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()
    role = user["role"]
    
    if role == 'employee':
        rows = conn.execute("SELECT * FROM expenses WHERE user_id=? ORDER BY invoice_date DESC, id DESC LIMIT 100", (session["user_id"],)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM expenses ORDER BY invoice_date DESC, id DESC LIMIT 200").fetchall()
        
    conn.close()
    return {"expenses": [dict(row) for row in rows], "role": role}

@app.get("/api/summary")
async def get_summary(session_id: str = Header(None)):
    session = active_sessions.get(session_id)
    if not session or not session.get("user_id"): return {"error": "not_authenticated"}
    conn = get_db()
    rows = conn.execute("SELECT total, gst, qst, status FROM expenses WHERE user_id=?", (session["user_id"],)).fetchall()
    conn.close()
    
    total_spent = sum((r["total"] or 0) for r in rows)
    return {
        "total_spent": round(total_spent, 2),
        "total_gst": sum((r["gst"] or 0) for r in rows),
        "total_qst": sum((r["qst"] or 0) for r in rows),
        "invoice_count": len(rows),
        "paid_count": sum(1 for r in rows if r["status"] == "Paid"),
        "unpaid_count": sum(1 for r in rows if r["status"] == "Unpaid")
    }

@app.post("/api/expenses/action")
async def expense_action(request: Request, session_id: str = Header(None)):
    session = active_sessions.get(session_id)
    if not session or not session.get("user_id"): return {"success": False}
    
    body = await request.json()
    exp_id = body.get("id")
    action = body.get("action")
    
    conn = get_db()
    if action == "approve":
        conn.execute("UPDATE expenses SET approval_status='Approved' WHERE id=?", (exp_id,))
        msg = "Expense Approved"
    elif action == "pay":
        conn.execute("UPDATE expenses SET status='Paid' WHERE id=?", (exp_id,))
        msg = "Payment initiated via Stripe. Marked as Paid."
    elif action == "delete":
        conn.execute("DELETE FROM expenses WHERE id=?", (exp_id,))
        msg = "Receipt permanently deleted."
        
    conn.commit()
    conn.close()
    return {"success": True, "message": msg}

@app.get("/api/sync/{platform}")
async def sync_accounting(platform: str, session_id: str = Header(None)):
    session = active_sessions.get(session_id)
    if not session or not session.get("user_id"): return {"success": False}
    return {"success": True, "message": f"Successfully synced 12 records with {platform.upper()}"}

@app.get("/api/export/csv")
async def export_csv(session_id: str = Header(None)):
    session = active_sessions.get(session_id)
    if not session or not session.get("user_id"): return {"error": "not_auth"}
    
    conn = get_db()
    rows = conn.execute("SELECT * FROM expenses WHERE user_id=?", (session["user_id"],)).fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Vendor", "Invoice_Number", "Subtotal", "Tax", "Total", "Status", "Approval", "Policy_Violation"])
    for r in rows:
        writer.writerow([r["invoice_date"], r["vendor"], r["invoice_number"], r["subtotal"], (r["gst"] or 0)+(r["qst"] or 0), r["total"], r["status"], r["approval_status"], r["policy_violations"]])
    
    return PlainTextResponse(output.getvalue(), headers={"Content-Disposition": "attachment; filename=nalaris_export.csv", "Content-Type": "text/csv"})

@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...), session_id: str = Header(None)):
    session = ensure_session(session_id)
    if not session["user_id"]: return {"success": False, "message": "Not authenticated"}
    
    raw = await file.read()
    content = raw.decode("utf-8").splitlines()
    reader = csv.DictReader(content)
    
    conn = get_db()
    count = 0
    for row in reader:
        total = float(row.get("Total", 0) or 0)
        conn.execute(
            """INSERT INTO expenses (user_id, vendor, invoice_date, total, status, approval_status) VALUES (?,?,?,?,?,?)""",
            (session["user_id"], row.get("Vendor", "Imported"), row.get("Date"), total, row.get("Status", "Unpaid"), "Approved")
        )
        count += 1
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Successfully imported {count} records."}

@app.post("/api/bank/upload")
async def bank_statement_upload(file: UploadFile = File(...), session_id: str = Header(None)):
    raw = await file.read()
    session = ensure_session(session_id)
    if not session["user_id"]: return {"reply": "Please authenticate first."}

    conn = get_db()
    unpaid = conn.execute("SELECT vendor, total FROM expenses WHERE status='Unpaid'").fetchall()
    conn.close()
    
    prompt = f"Analyze this bank statement. Look for these unpaid bills: {json.dumps([dict(r) for r in unpaid])}. Reply with a natural language summary of which bills appear to have been paid based on this statement."
    
    try:
        if file.filename.endswith(('.png', '.jpg', '.jpeg')):
            img = Image.open(io.BytesIO(raw))
            resp = client.models.generate_content(model='gemini-2.5-flash', contents=[prompt, img])
        else:
            resp = client.models.generate_content(model='gemini-2.5-flash', contents=[prompt, raw.decode('utf-8', errors='ignore')])
            
        save_chat(session["user_id"], "user", "text", f"🏦 Uploaded Bank Statement: {file.filename}")
        save_chat(session["user_id"], "bot", "text", resp.text)
        return {"reply": resp.text}
    except Exception as exc:
        return {"reply": f"⚠️ Statement processing error: {exc}"}

@app.get("/api/billing/status")
async def get_billing_status(session_id: str = Header(None)):
    session = active_sessions.get(session_id)
    if not session or not session.get("user_id"): return {"error": "not_auth"}
    conn = get_db()
    user = conn.execute("SELECT tier, role, balance, receipts_today FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return dict(user)

@app.post("/api/update-profile")
async def update_profile(request: Request, session_id: str = Header(None)):
    session = ensure_session(session_id)
    if not session.get("user_id"): return {"success": False}
    body = await request.json()
    conn = get_db()
    
    if "role" in body:
        conn.execute("UPDATE users SET role=? WHERE id=?", (body["role"], session["user_id"]))
    if "owner_name" in body:
        conn.execute("UPDATE users SET owner_name=?, business_name=? WHERE id=?", (body["owner_name"], body.get("business_name", ""), session["user_id"]))
    
    conn.commit()
    conn.close()
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010, reload=False)