import os
import re
import logging
import html as html_lib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from config import TELEGRAM_TOKEN, TELEGRAM_CHANNEL_ID
from services.database import (
    register_user, get_user_count,
    get_opportunities_by_category, get_unsent_opportunities, mark_sent
)
from services.ai_chat import (
    chat_completion, generate_ats_resume, SYSTEM_PROMPT,
    async_chat_completion, async_generate_ats_resume
)
from services.resume_export import export_pdf, export_docx, export_txt

log = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "business_grants": "Business Grants",
    "student_scholarships": "Student Scholarships",
    "nonprofit_funding": "Non-Profit Funding",
}
MAX_MSG_LEN = 4000


def escape(text: str) -> str:
    if not text:
        return ""
    return html_lib.escape(str(text))


def format_opportunity_full(opp: dict) -> str:
    cat_label = CATEGORY_LABELS.get(opp.get("category", ""), opp.get("category", ""))
    title = escape(opp.get("title", ""))
    url = opp.get("url", "")
    source = escape(opp.get("source", ""))
    parts = [f"<b>{title}</b>", ""]
    summary = opp.get("summary") or opp.get("description", "")
    if summary:
        parts.extend([escape(summary), ""])
    if opp.get("level"):
        parts.append(f"<b>Level:</b> {escape(opp['level'])}")
    if opp.get("host_country"):
        parts.append(f"<b>Study In:</b> {escape(opp['host_country'])}")
    if opp.get("amount"):
        parts.append(f"<b>Award:</b> {escape(opp['amount'])}")
    if opp.get("deadline"):
        parts.append(f"<b>Deadline:</b> {escape(opp['deadline'])}")
    if opp.get("eligibility"):
        parts.append(f"\n<b>Eligibility:</b>\n{escape(opp['eligibility'])}")
    if opp.get("benefits"):
        parts.append(f"\n<b>Benefits:</b>\n{escape(opp['benefits'])}")
    parts.append(f"\n<b>Category:</b> {escape(cat_label)}")
    parts.append(f"<b>Source:</b> {escape(source)}")
    parts.append(f'\n<a href="{escape(url)}">Apply Here / View Full Details</a>')
    return "\n".join(parts)


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]
    chunks = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            chunks.append(text)
            break
        cut = text[:MAX_MSG_LEN]
        split_pos = cut.rfind("\n\n")
        if split_pos < 500:
            split_pos = cut.rfind("\n")
        if split_pos < 500:
            split_pos = MAX_MSG_LEN
        chunks.append(text[:split_pos].rstrip())
        text = text[split_pos:].lstrip()
    return chunks


async def send_full_message(bot, chat_id, text, reply_markup=None):
    import asyncio, re as _re
    parts = split_message(text)
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        for attempt in range(3):
            try:
                await bot.send_message(chat_id=chat_id, text=part, parse_mode="HTML",
                                       disable_web_page_preview=True, reply_markup=markup)
                break
            except Exception as e:
                err_str = str(e)
                retry_match = _re.search(r'Retry in (\d+)', err_str)
                if retry_match:
                    wait = int(retry_match.group(1)) + 1
                    log.warning("Flood control, waiting %ds...", wait)
                    await asyncio.sleep(wait)
                elif attempt < 2:
                    try:
                        await bot.send_message(chat_id=chat_id, text=part,
                                               disable_web_page_preview=True, reply_markup=markup)
                        break
                    except Exception:
                        await asyncio.sleep(2)
                else:
                    log.error("Send failed after retries: %s", e)


async def send_opportunities(bot, chat_id, opps):
    if not opps:
        await bot.send_message(chat_id, "No opportunities found yet. I'm still gathering data — check back soon!")
        return
    for opp in opps:
        await send_full_message(bot, chat_id, format_opportunity_full(opp))


async def do_search(bot, chat_id, keyword):
    from services.database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE title LIKE ? OR description LIKE ? OR summary LIKE ? ORDER BY posted_at DESC LIMIT 5",
        (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
    ).fetchall()
    conn.close()
    if not rows:
        await bot.send_message(chat_id, f"No results for '{escape(keyword)}'. Try different keywords.", parse_mode="HTML")
        return
    await bot.send_message(chat_id, f"Found {len(rows)} result(s) for '<b>{escape(keyword)}</b>':", parse_mode="HTML")
    for row in rows:
        await send_full_message(bot, chat_id, format_opportunity_full(dict(row)))


# ─── WELCOME ───

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "")
    context.user_data.clear()
    context.user_data["chat_history"] = [{"role": "system", "content": SYSTEM_PROMPT}]

    await update.message.reply_text(
        f"Hey {escape(user.first_name)}! 👋\n\n"
        "I'm your AI-powered assistant. Just tell me what you need — no commands required!\n\n"
        "<b>I can help you with:</b>\n\n"
        "🎓 <b>Scholarships & Grants</b>\n"
        "Find fully funded scholarships worldwide for Kenyan students. "
        "Just say something like \"find me scholarships in Germany\" or \"show me PhD grants\".\n\n"
        "📄 <b>ATS Resume Builder</b>\n"
        "Build a professional resume that passes Applicant Tracking Systems. "
        "Just say \"help me write a resume\" and I'll guide you through it.\n\n"
        "<i>Go ahead, type anything!</i>",
        parse_mode="HTML",
    )


# ─── RESUME DOWNLOAD BUTTONS ───

async def resume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("resume:", "")

    resume = context.user_data.get("generated_resume")
    if not resume:
        await query.edit_message_text("No resume found. Tell me you'd like to build one!")
        return

    if action in ("pdf", "docx", "txt"):
        await context.bot.send_chat_action(query.message.chat_id, "upload_document")
        try:
            name = context.user_data.get("resume_data", {}).get("name", "resume").replace(" ", "_")
            if action == "pdf":
                path = export_pdf(resume, name)
            elif action == "docx":
                path = export_docx(resume, name)
            else:
                path = export_txt(resume, name)
            with open(path, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id, document=f,
                    filename=os.path.basename(path),
                    caption=f"Your ATS resume ({action.upper()})",
                )
            os.unlink(path)
        except Exception as e:
            log.error("Export error: %s", e)
            await context.bot.send_message(query.message.chat_id, f"Error generating file: {e}")

    elif action == "download_all":
        await context.bot.send_chat_action(query.message.chat_id, "upload_document")
        name = context.user_data.get("resume_data", {}).get("name", "resume").replace(" ", "_")
        for fmt, fn in [("pdf", export_pdf), ("docx", export_docx), ("txt", export_txt)]:
            try:
                path = fn(resume, name)
                with open(path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id, document=f,
                        filename=os.path.basename(path),
                        caption=f"Your ATS resume ({fmt.upper()})",
                    )
                os.unlink(path)
            except Exception as e:
                log.error("Export %s error: %s", fmt, e)


# ─── MAIN AI HANDLER ───

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "")
    text = update.message.text.strip()
    log.info("Message from %s (%s): %s", user.first_name, user.id, text[:100])

    if not text:
        return

    try:
        await context.bot.send_chat_action(update.message.chat_id, "typing")
    except Exception:
        pass

    history = context.user_data.get("chat_history", [])
    if not history:
        history = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inject DB context for scholarship queries
    scholarship_keywords = ["scholarship", "grant", "funding", "bursary", "fellowship",
                            "opportunity", "study abroad", "fully funded", "masters", "phd",
                            "bachelors", "university", "college"]
    if any(kw in text.lower() for kw in scholarship_keywords):
        from services.database import get_conn
        conn = get_conn()
        count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        conn.close()
        context_msg = f"[SYSTEM NOTE: The scholarship database currently has {count} opportunities. Use [SEARCH: keyword] to show results, [SHOW_LATEST] for latest, or [SHOW_CATEGORY: category] for category browsing.]"
        history.append({"role": "system", "content": context_msg})

    # Collect resume data from conversation
    resume_data = context.user_data.get("resume_data", {})
    if resume_data:
        resume_info = "\n".join(f"{k}: {v}" for k, v in resume_data.items() if v)
        if resume_info:
            history.append({"role": "system", "content": f"[SYSTEM NOTE: Resume data collected so far:\n{resume_info}]"})

    history.append({"role": "user", "content": text})

    if len(history) > 30:
        history = [history[0]] + history[-28:]

    response = await async_chat_completion(history, max_tokens=1000)
    history.append({"role": "assistant", "content": response})
    context.user_data["chat_history"] = history

    # Parse AI actions from response
    clean_response = response
    actions_done = False

    # Handle [GENERATE_RESUME]
    if "[GENERATE_RESUME]" in response:
        clean_response = response.replace("[GENERATE_RESUME]", "").strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))

        await context.bot.send_message(update.message.chat_id, "✍️ Generating your ATS-optimized resume...")
        await context.bot.send_chat_action(update.message.chat_id, "typing")

        resume_data = await _async_extract_resume_data(history)
        context.user_data["resume_data"] = resume_data
        resume_text = await async_generate_ats_resume(resume_data)
        context.user_data["generated_resume"] = resume_text

        await send_full_message(context.bot, update.message.chat_id, f"<pre>{escape(resume_text)}</pre>")

        keyboard = [
            [InlineKeyboardButton("📄 PDF", callback_data="resume:pdf"),
             InlineKeyboardButton("📝 DOCX", callback_data="resume:docx"),
             InlineKeyboardButton("📋 TXT", callback_data="resume:txt")],
            [InlineKeyboardButton("⬇️ Download All Formats", callback_data="resume:download_all")],
        ]
        await update.message.reply_text(
            "<b>Resume ready!</b> Choose a download format:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        actions_done = True

    # Handle [SEARCH: keyword]
    search_match = re.search(r'\[SEARCH:\s*(.+?)\]', response)
    if search_match:
        keyword = search_match.group(1).strip()
        clean_response = re.sub(r'\[SEARCH:\s*.+?\]', '', clean_response).strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
        await do_search(context.bot, update.message.chat_id, keyword)
        actions_done = True

    # Handle [SHOW_LATEST]
    if "[SHOW_LATEST]" in response:
        clean_response = clean_response.replace("[SHOW_LATEST]", "").strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
        from services.database import get_conn
        conn = get_conn()
        rows = conn.execute("SELECT * FROM opportunities ORDER BY posted_at DESC LIMIT 5").fetchall()
        conn.close()
        await send_opportunities(context.bot, update.message.chat_id, [dict(r) for r in rows])
        actions_done = True

    # Handle [SHOW_CATEGORY: xxx]
    cat_match = re.search(r'\[SHOW_CATEGORY:\s*(.+?)\]', response)
    if cat_match:
        category = cat_match.group(1).strip()
        clean_response = re.sub(r'\[SHOW_CATEGORY:\s*.+?\]', '', clean_response).strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
        opps = get_opportunities_by_category(category, limit=5)
        await send_opportunities(context.bot, update.message.chat_id, opps)
        actions_done = True

    # Regular AI response (no actions)
    if not actions_done:
        clean_response = re.sub(r'\[.*?\]', '', clean_response).strip()
        if clean_response:
            try:
                await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
            except Exception as e:
                log.error("Failed to send response: %s", e)
                try:
                    await update.message.reply_text(clean_response[:4000])
                except Exception:
                    pass


async def _async_extract_resume_data(history: list[dict]) -> dict:
    """Extract resume fields from conversation history using async AI."""
    full_text = "\n".join(
        m["content"] for m in history
        if m["role"] == "user"
    )

    data = {}
    for msg in history:
        if msg["role"] != "user":
            continue
        content = msg["content"]

        if "@" in content and not data.get("email"):
            emails = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', content)
            if emails:
                data["email"] = emails[0]

        if re.search(r'\+?\d[\d\s-]{8,}', content) and not data.get("phone"):
            phones = re.findall(r'\+?\d[\d\s-]{8,}', content)
            if phones:
                data["phone"] = phones[0].strip()

    extract_prompt = f"""Extract resume information from this conversation. Return ONLY the data in this exact format (leave blank if not mentioned):

name: 
email: 
phone: 
location: 
target_job: 
summary: 
experience: 
education: 
skills: 

Conversation:
{full_text[-3000:]}"""

    messages = [{"role": "user", "content": extract_prompt}]
    result = await async_chat_completion(messages, max_tokens=800)

    for line in result.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if key in ["name", "email", "phone", "location", "target_job", "summary", "experience", "education", "skills"]:
                if value and value.lower() not in ["not provided", "not mentioned", "n/a", ""]:
                    data[key] = value

    return data


# ─── CHANNEL POSTING ───

async def post_to_channel(app: Application):
    if not TELEGRAM_CHANNEL_ID:
        return
    import asyncio
    opps = get_unsent_opportunities(limit=20)
    if not opps:
        return
    bot_info = await app.bot.get_me()
    for opp in opps:
        try:
            text = format_opportunity_full(opp)
            keyboard = [[InlineKeyboardButton(
                "Chat with me for Scholarships + Free Resume Builder!",
                url=f"https://t.me/{bot_info.username}"
            )]]
            await send_full_message(app.bot, TELEGRAM_CHANNEL_ID, text,
                                    reply_markup=InlineKeyboardMarkup(keyboard))
            mark_sent(opp["uid"])
            await asyncio.sleep(3)
        except Exception as e:
            log.error("Channel post error: %s", e)
            await asyncio.sleep(5)


# ─── BUILD APP ───

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Bot error: %s", context.error, exc_info=context.error)


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(resume_callback, pattern=r"^resume:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    return app
