import time
import os
import logging
import html as html_lib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from config import TELEGRAM_TOKEN, TELEGRAM_CHANNEL_ID, FREE_DAILY_LIMIT, PREMIUM_PRICE, CATEGORIES
from services.database import (
    register_user, get_user, increment_daily_count, is_premium,
    get_opportunities_by_category, get_user_count, get_unsent_opportunities, mark_sent
)
from services.ai_chat import chat_completion, generate_ats_resume, SYSTEM_PROMPT
from services.resume_export import export_pdf, export_docx, export_txt

log = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "business_grants": "Business Grants",
    "student_scholarships": "Student Scholarships",
    "nonprofit_funding": "Non-Profit Funding",
}

MAX_MSG_LEN = 4000
RESUME_FIELDS = ["name", "email", "phone", "location", "target_job", "summary", "experience", "education", "skills"]
RESUME_PROMPTS = {
    "name": "What is your <b>full name</b>?",
    "email": "What is your <b>email address</b>?",
    "phone": "What is your <b>phone number</b>?",
    "location": "What is your <b>location</b> (city, country)?",
    "target_job": "What <b>job title</b> are you applying for?",
    "summary": "Write a brief <b>professional summary</b> (2-3 sentences about your experience and goals).\n\nOr type <b>skip</b> and AI will write one for you.",
    "experience": "List your <b>work experience</b>. Include:\n- Job title, company, dates\n- Key responsibilities/achievements\n\nSeparate multiple jobs with a blank line.\nType <b>skip</b> if none.",
    "education": "List your <b>education</b>:\n- Degree, institution, dates\n\nSeparate multiple entries with a blank line.",
    "skills": "List your <b>key skills</b> (comma-separated).\nExample: Python, Project Management, Data Analysis, Leadership",
}


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
    parts = split_message(text)
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        try:
            await bot.send_message(chat_id=chat_id, text=part, parse_mode="HTML",
                                   disable_web_page_preview=True, reply_markup=markup)
        except Exception:
            try:
                await bot.send_message(chat_id=chat_id, text=part,
                                       disable_web_page_preview=True, reply_markup=markup)
            except Exception as e2:
                log.error("Send failed: %s", e2)


# ─── MAIN MENU ───

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "")
    context.user_data.clear()

    keyboard = [
        [InlineKeyboardButton("Scholarships & Grants", callback_data="menu:scholarships")],
        [InlineKeyboardButton("ATS Resume Builder", callback_data="menu:resume")],
    ]
    await update.message.reply_text(
        f"<b>Welcome, {escape(user.first_name)}!</b>\n\n"
        "I'm your AI-powered assistant for Kenyan students and professionals.\n\n"
        "Choose what you need:\n\n"
        "<b>Scholarships & Grants</b> — Find fully funded opportunities worldwide\n"
        "<b>ATS Resume Builder</b> — Create professional resumes that pass ATS systems\n\n"
        "You can also just <b>type naturally</b> and I'll understand what you need!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>How to use this bot:</b>\n\n"
        "<b>Scholarship Commands:</b>\n"
        "/scholarships — Browse student scholarships\n"
        "/grants — Business grants\n"
        "/nonprofit — Non-profit funding\n"
        "/latest — Latest opportunities\n"
        "/search &lt;keyword&gt; — Search (e.g. /search DAAD)\n\n"
        "<b>Resume Commands:</b>\n"
        "/resume — Start building an ATS resume\n"
        "/myresume — View your saved resume\n\n"
        "<b>Other:</b>\n"
        "/start — Main menu\n"
        "/premium — Upgrade info\n"
        "/stats — Bot statistics\n\n"
        "Or just <b>type any message</b> and AI will help you!",
        parse_mode="HTML",
    )


# ─── MENU CALLBACKS ───

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("menu:", "")

    if action == "scholarships":
        keyboard = [
            [InlineKeyboardButton("Student Scholarships", callback_data="cat:student_scholarships")],
            [InlineKeyboardButton("Business Grants", callback_data="cat:business_grants")],
            [InlineKeyboardButton("Non-Profit Funding", callback_data="cat:nonprofit_funding")],
            [InlineKeyboardButton("Latest Opportunities", callback_data="action:latest")],
            [InlineKeyboardButton("Search Scholarships", callback_data="action:search_prompt")],
            [InlineKeyboardButton("Back to Menu", callback_data="action:back")],
        ]
        await query.edit_message_text(
            "<b>Scholarships & Grants</b>\n\n"
            "I scrape 10+ websites every hour to find scholarships for Kenyan citizens worldwide.\n\n"
            "Choose a category or action:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "resume":
        keyboard = [
            [InlineKeyboardButton("Build New Resume", callback_data="resume:start")],
            [InlineKeyboardButton("View My Resume", callback_data="resume:view")],
            [InlineKeyboardButton("Download as PDF", callback_data="resume:pdf")],
            [InlineKeyboardButton("Download as DOCX", callback_data="resume:docx")],
            [InlineKeyboardButton("Download as TXT", callback_data="resume:txt")],
            [InlineKeyboardButton("Back to Menu", callback_data="action:back")],
        ]
        await query.edit_message_text(
            "<b>ATS Resume Builder</b>\n\n"
            "I'll help you create a professional resume optimized for Applicant Tracking Systems (ATS).\n\n"
            "ATS-friendly resumes use:\n"
            "• Clean formatting (no tables/graphics)\n"
            "• Strong action verbs with metrics\n"
            "• Keywords matching the job description\n"
            "• Standard section headings\n\n"
            "Choose an option:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("action:", "")

    if action == "back":
        keyboard = [
            [InlineKeyboardButton("Scholarships & Grants", callback_data="menu:scholarships")],
            [InlineKeyboardButton("ATS Resume Builder", callback_data="menu:resume")],
        ]
        await query.edit_message_text(
            "<b>Main Menu</b>\n\nChoose what you need:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "latest":
        await query.edit_message_text("Fetching latest opportunities...")
        from services.database import get_conn
        conn = get_conn()
        rows = conn.execute("SELECT * FROM opportunities ORDER BY posted_at DESC LIMIT 5").fetchall()
        conn.close()
        if not rows:
            await context.bot.send_message(query.message.chat_id, "No opportunities yet. Check back soon!")
        else:
            for row in rows:
                await send_full_message(context.bot, query.message.chat_id, format_opportunity_full(dict(row)))

    elif action == "search_prompt":
        await query.edit_message_text(
            "Type your search query as a message.\n\n"
            "Examples:\n• <i>DAAD scholarship Germany</i>\n• <i>Fully funded PhD UK</i>\n• <i>Business grant Kenya</i>",
            parse_mode="HTML",
        )
        context.user_data["awaiting_search"] = True


# ─── SCHOLARSHIP HANDLERS ───

async def callback_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("cat:", "")
    user_id = query.from_user.id
    register_user(user_id, query.from_user.username or "")

    opps = get_opportunities_by_category(category, limit=5)
    if not opps:
        await context.bot.send_message(query.message.chat_id, "No opportunities in this category yet. Check back soon!")
        return
    for opp in opps:
        await send_full_message(context.bot, query.message.chat_id, format_opportunity_full(opp))


async def cmd_scholarships(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opps = get_opportunities_by_category("student_scholarships", limit=5)
    if not opps:
        await update.message.reply_text("No scholarships yet. Check back soon!")
        return
    for opp in opps:
        await send_full_message(context.bot, update.message.chat_id, format_opportunity_full(opp))


async def cmd_grants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opps = get_opportunities_by_category("business_grants", limit=5)
    if not opps:
        await update.message.reply_text("No grants yet. Check back soon!")
        return
    for opp in opps:
        await send_full_message(context.bot, update.message.chat_id, format_opportunity_full(opp))


async def cmd_nonprofit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opps = get_opportunities_by_category("nonprofit_funding", limit=5)
    if not opps:
        await update.message.reply_text("No nonprofit funding yet. Check back soon!")
        return
    for opp in opps:
        await send_full_message(context.bot, update.message.chat_id, format_opportunity_full(opp))


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from services.database import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT * FROM opportunities ORDER BY posted_at DESC LIMIT 5").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No opportunities yet!")
        return
    for row in rows:
        await send_full_message(context.bot, update.message.chat_id, format_opportunity_full(dict(row)))


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search &lt;keyword&gt;\nExample: /search DAAD", parse_mode="HTML")
        return
    keyword = " ".join(context.args)
    await do_search(context.bot, update.message.chat_id, keyword)


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


# ─── RESUME BUILDER ───

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["resume_mode"] = True
    context.user_data["resume_step"] = 0
    context.user_data["resume_data"] = {}
    field = RESUME_FIELDS[0]
    await update.message.reply_text(
        "<b>ATS Resume Builder</b>\n\n"
        "I'll ask you a few questions to build your resume.\n"
        "You can type <b>skip</b> for optional fields.\n\n"
        f"{RESUME_PROMPTS[field]}",
        parse_mode="HTML",
    )


async def resume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("resume:", "")

    if action == "start":
        context.user_data["resume_mode"] = True
        context.user_data["resume_step"] = 0
        context.user_data["resume_data"] = {}
        field = RESUME_FIELDS[0]
        await query.edit_message_text(
            f"<b>ATS Resume Builder</b>\n\nLet's build your resume!\n\n{RESUME_PROMPTS[field]}",
            parse_mode="HTML",
        )

    elif action == "view":
        resume = context.user_data.get("generated_resume")
        if not resume:
            await query.edit_message_text("No resume generated yet. Use 'Build New Resume' first.")
            return
        await query.edit_message_text("Here's your resume:")
        await send_full_message(context.bot, query.message.chat_id, f"<pre>{escape(resume)}</pre>")

    elif action in ("pdf", "docx", "txt"):
        resume = context.user_data.get("generated_resume")
        if not resume:
            await query.edit_message_text("No resume generated yet. Use 'Build New Resume' first.")
            return
        await query.edit_message_text(f"Generating {action.upper()} file...")
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
                    chat_id=query.message.chat_id,
                    document=f,
                    filename=os.path.basename(path),
                    caption=f"Your ATS resume ({action.upper()})",
                )
            os.unlink(path)
        except Exception as e:
            log.error("Export error: %s", e)
            await context.bot.send_message(query.message.chat_id, f"Error generating file: {e}")

    elif action == "download_all":
        resume = context.user_data.get("generated_resume")
        if not resume:
            return
        name = context.user_data.get("resume_data", {}).get("name", "resume").replace(" ", "_")
        for fmt, export_fn in [("pdf", export_pdf), ("docx", export_docx), ("txt", export_txt)]:
            try:
                path = export_fn(resume, name)
                with open(path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id, document=f,
                        filename=os.path.basename(path),
                        caption=f"Your ATS resume ({fmt.upper()})",
                    )
                os.unlink(path)
            except Exception as e:
                log.error("Export %s error: %s", fmt, e)


async def handle_resume_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process resume builder step-by-step input."""
    step = context.user_data.get("resume_step", 0)
    text = update.message.text.strip()

    field = RESUME_FIELDS[step]
    if text.lower() != "skip":
        context.user_data.setdefault("resume_data", {})[field] = text
    else:
        context.user_data.setdefault("resume_data", {})[field] = ""

    step += 1
    context.user_data["resume_step"] = step

    if step < len(RESUME_FIELDS):
        next_field = RESUME_FIELDS[step]
        await update.message.reply_text(RESUME_PROMPTS[next_field], parse_mode="HTML")
    else:
        await update.message.reply_text("Generating your ATS-optimized resume with AI... Please wait.")
        context.user_data["resume_mode"] = False

        resume_text = generate_ats_resume(context.user_data["resume_data"])
        context.user_data["generated_resume"] = resume_text

        await send_full_message(context.bot, update.message.chat_id, f"<pre>{escape(resume_text)}</pre>")

        keyboard = [
            [InlineKeyboardButton("Download PDF", callback_data="resume:pdf"),
             InlineKeyboardButton("Download DOCX", callback_data="resume:docx")],
            [InlineKeyboardButton("Download TXT", callback_data="resume:txt"),
             InlineKeyboardButton("Download All", callback_data="resume:download_all")],
            [InlineKeyboardButton("Build New Resume", callback_data="resume:start")],
            [InlineKeyboardButton("Back to Menu", callback_data="action:back")],
        ]
        await update.message.reply_text(
            "<b>Resume generated!</b> Choose a download format:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# ─── AI CONVERSATION HANDLER ───

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any text message with AI — routes to search, resume, or general chat."""
    user = update.effective_user
    register_user(user.id, user.username or "")
    text = update.message.text.strip()

    if context.user_data.get("resume_mode"):
        await handle_resume_input(update, context)
        return

    if context.user_data.get("awaiting_search"):
        context.user_data["awaiting_search"] = False
        await do_search(context.bot, update.message.chat_id, text)
        return

    await context.bot.send_chat_action(update.message.chat_id, "typing")

    history = context.user_data.get("chat_history", [])
    if not history:
        history.append({"role": "system", "content": SYSTEM_PROMPT})
    history.append({"role": "user", "content": text})

    if len(history) > 20:
        history = [history[0]] + history[-18:]

    response = chat_completion(history, max_tokens=800)
    history.append({"role": "assistant", "content": response})
    context.user_data["chat_history"] = history

    resp_lower = response.lower()
    if any(kw in text.lower() for kw in ["resume", "cv", "ats"]):
        if any(kw in resp_lower for kw in ["let's start", "build", "create", "let me help"]):
            context.user_data["resume_mode"] = True
            context.user_data["resume_step"] = 0
            context.user_data["resume_data"] = {}
            response += f"\n\n{RESUME_PROMPTS['name']}"

    if any(kw in text.lower() for kw in ["search", "find", "scholarship", "grant", "funding"]):
        for word in text.split():
            if len(word) > 3 and word.lower() not in ["search", "find", "scholarship", "grant", "funding", "please", "help", "want", "need", "looking"]:
                from services.database import get_conn
                conn = get_conn()
                rows = conn.execute(
                    "SELECT COUNT(*) FROM opportunities WHERE title LIKE ? OR description LIKE ?",
                    (f"%{word}%", f"%{word}%")
                ).fetchone()
                conn.close()
                if rows[0] > 0:
                    response += f"\n\nI found {rows[0]} opportunities matching '{word}'. Type /search {word} to see them."
                    break

    await send_full_message(context.bot, update.message.chat_id, escape(response))


# ─── OTHER COMMANDS ───

async def cmd_myresume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resume = context.user_data.get("generated_resume")
    if not resume:
        await update.message.reply_text("No resume generated yet. Use /resume to build one.")
        return
    await send_full_message(context.bot, update.message.chat_id, f"<pre>{escape(resume)}</pre>")
    keyboard = [
        [InlineKeyboardButton("PDF", callback_data="resume:pdf"),
         InlineKeyboardButton("DOCX", callback_data="resume:docx"),
         InlineKeyboardButton("TXT", callback_data="resume:txt")],
    ]
    await update.message.reply_text("Download:", reply_markup=InlineKeyboardMarkup(keyboard))


async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"<b>Premium Access - {PREMIUM_PRICE}</b>\n\n"
        "<b>Benefits:</b>\n"
        "- Unlimited daily opportunity views\n"
        "- Unlimited AI resume generations\n"
        "- Priority notifications\n"
        "- Advanced keyword search\n"
        "- All download formats\n\n"
        "Contact the admin for manual activation.",
        parse_mode="HTML",
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_count = get_user_count()
    from services.database import get_conn
    conn = get_conn()
    opp_count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    cat_counts = conn.execute("SELECT category, COUNT(*) FROM opportunities GROUP BY category").fetchall()
    conn.close()
    stats = "<b>Bot Stats:</b>\n\n"
    stats += f"Total users: {user_count}\n"
    stats += f"Opportunities tracked: {opp_count}\n"
    stats += f"Update frequency: Every hour\n\n<b>By Category:</b>\n"
    for row in cat_counts:
        stats += f"- {CATEGORY_LABELS.get(row[0], row[0])}: {row[1]}\n"
    await update.message.reply_text(stats, parse_mode="HTML")


# ─── CHANNEL POSTING ───

async def post_to_channel(app: Application):
    if not TELEGRAM_CHANNEL_ID:
        log.warning("No TELEGRAM_CHANNEL_ID set")
        return
    opps = get_unsent_opportunities(limit=50)
    bot_info = await app.bot.get_me()
    for opp in opps:
        try:
            text = format_opportunity_full(opp)
            keyboard = [[InlineKeyboardButton(
                "Get Scholarships + Free Resume Builder!",
                url=f"https://t.me/{bot_info.username}"
            )]]
            await send_full_message(app.bot, TELEGRAM_CHANNEL_ID, text,
                                    reply_markup=InlineKeyboardMarkup(keyboard))
            mark_sent(opp["uid"])
        except Exception as e:
            log.error("Channel post error: %s", e)


# ─── BUILD APP ───

def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("myresume", cmd_myresume))
    app.add_handler(CommandHandler("scholarships", cmd_scholarships))
    app.add_handler(CommandHandler("grants", cmd_grants))
    app.add_handler(CommandHandler("nonprofit", cmd_nonprofit))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("premium", cmd_premium))
    app.add_handler(CommandHandler("stats", cmd_stats))

    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(action_callback, pattern=r"^action:"))
    app.add_handler(CallbackQueryHandler(callback_category, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(resume_callback, pattern=r"^resume:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message))

    return app
