import time
import logging
import html as html_lib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from config import TELEGRAM_TOKEN, TELEGRAM_CHANNEL_ID, FREE_DAILY_LIMIT, PREMIUM_PRICE, CATEGORIES
from services.database import (
    register_user, get_user, increment_daily_count, is_premium,
    get_opportunities_by_category, get_user_count, get_unsent_opportunities, mark_sent
)

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
    """Build a rich, complete message with all info and links. No truncation."""
    cat_label = CATEGORY_LABELS.get(opp.get("category", ""), opp.get("category", ""))
    title = escape(opp.get("title", ""))
    url = opp.get("url", "")
    source = escape(opp.get("source", ""))

    parts = [f"<b>{title}</b>"]
    parts.append("")

    summary = opp.get("summary") or opp.get("description", "")
    if summary:
        parts.append(f"{escape(summary)}")
        parts.append("")

    if opp.get("level"):
        parts.append(f"<b>Level:</b> {escape(opp['level'])}")

    if opp.get("host_country"):
        parts.append(f"<b>Study In:</b> {escape(opp['host_country'])}")

    if opp.get("amount"):
        parts.append(f"<b>Award:</b> {escape(opp['amount'])}")

    if opp.get("deadline"):
        parts.append(f"<b>Deadline:</b> {escape(opp['deadline'])}")

    if opp.get("eligibility"):
        elig = escape(opp["eligibility"])
        parts.append(f"\n<b>Eligibility:</b>\n{elig}")

    if opp.get("benefits"):
        ben = escape(opp["benefits"])
        parts.append(f"\n<b>Benefits:</b>\n{ben}")

    parts.append(f"\n<b>Category:</b> {escape(cat_label)}")
    parts.append(f"<b>Source:</b> {escape(source)}")
    parts.append(f'\n<a href="{escape(url)}">Apply Here / View Full Details</a>')

    return "\n".join(parts)


def split_message(text: str) -> list[str]:
    """Split long messages at safe boundaries to stay under Telegram's 4096 limit."""
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

        chunk = text[:split_pos].rstrip()
        text = text[split_pos:].lstrip()
        chunks.append(chunk)

    return chunks


async def send_full_message(bot, chat_id, text, reply_markup=None):
    """Send a message, splitting into multiple parts if needed."""
    parts = split_message(text)
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
            )
        except Exception as e:
            log.error("Error sending message part %d: %s", i, e)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    disable_web_page_preview=True,
                    reply_markup=markup,
                )
            except Exception as e2:
                log.error("Fallback send also failed: %s", e2)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "")
    await update.message.reply_text(
        "<b>Welcome to Kenya Scholarships Bot!</b>\n\n"
        "I find scholarships, grants, and funding opportunities for Kenyan citizens "
        "from around the globe and summarize them in plain English.\n\n"
        f"Free users get {FREE_DAILY_LIMIT} opportunities per day.\n"
        f"Upgrade to Premium ({PREMIUM_PRICE}) for unlimited access.\n\n"
        "<b>Commands:</b>\n"
        "/browse - Browse by category\n"
        "/latest - Latest opportunities\n"
        "/scholarships - Student scholarships\n"
        "/grants - Business grants\n"
        "/nonprofit - Non-profit funding\n"
        "/search &lt;keyword&gt; - Search opportunities\n"
        "/premium - Upgrade to premium\n"
        "/stats - Bot statistics\n"
        "/help - Show this message",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"cat:{key}")]
        for key, label in CATEGORY_LABELS.items()
    ]
    await update.message.reply_text(
        "Choose a category:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_category_view(bot, chat_id, user_id, username, category):
    register_user(user_id, username)

    if not is_premium(user_id):
        count = increment_daily_count(user_id)
        if count > FREE_DAILY_LIMIT:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"You've reached your daily limit of {FREE_DAILY_LIMIT} free views.\n\n"
                    f"Upgrade to Premium ({PREMIUM_PRICE}) for unlimited access!\n"
                    f"Use /premium to upgrade."
                ),
                parse_mode="HTML",
            )
            return

    opps = get_opportunities_by_category(category, limit=5)
    if not opps:
        await bot.send_message(chat_id=chat_id, text="No opportunities found in this category yet. Check back soon!")
        return

    for opp in opps:
        text = format_opportunity_full(opp)
        await send_full_message(bot, chat_id, text)


async def callback_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("cat:", "")
    await handle_category_view(
        context.bot, query.message.chat_id,
        query.from_user.id, query.from_user.username or "",
        category,
    )


async def cmd_scholarships(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_category_view(
        context.bot, update.message.chat_id,
        update.effective_user.id, update.effective_user.username or "",
        "student_scholarships",
    )


async def cmd_grants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_category_view(
        context.bot, update.message.chat_id,
        update.effective_user.id, update.effective_user.username or "",
        "business_grants",
    )


async def cmd_nonprofit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_category_view(
        context.bot, update.message.chat_id,
        update.effective_user.id, update.effective_user.username or "",
        "nonprofit_funding",
    )


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username or "")

    if not is_premium(user_id):
        count = increment_daily_count(user_id)
        if count > FREE_DAILY_LIMIT:
            await update.message.reply_text(
                f"Daily limit reached ({FREE_DAILY_LIMIT} free views).\n"
                f"Use /premium to upgrade for unlimited access!",
            )
            return

    from services.database import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT * FROM opportunities ORDER BY posted_at DESC LIMIT 5").fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No opportunities yet. The bot is still gathering data!")
        return

    for row in rows:
        text = format_opportunity_full(dict(row))
        await send_full_message(context.bot, update.message.chat_id, text)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username or "")

    if not context.args:
        await update.message.reply_text("Usage: /search &lt;keyword&gt;\nExample: /search DAAD", parse_mode="HTML")
        return

    keyword = " ".join(context.args)

    if not is_premium(user_id):
        count = increment_daily_count(user_id)
        if count > FREE_DAILY_LIMIT:
            await update.message.reply_text(
                f"Daily limit reached ({FREE_DAILY_LIMIT} free views).\nUse /premium to upgrade!",
            )
            return

    from services.database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE title LIKE ? OR description LIKE ? OR summary LIKE ? ORDER BY posted_at DESC LIMIT 5",
        (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(f"No results found for '{escape(keyword)}'. Try different keywords.", parse_mode="HTML")
        return

    await update.message.reply_text(f"Found {len(rows)} result(s) for '<b>{escape(keyword)}</b>':", parse_mode="HTML")
    for row in rows:
        text = format_opportunity_full(dict(row))
        await send_full_message(context.bot, update.message.chat_id, text)


async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"<b>Premium Access - {PREMIUM_PRICE}</b>\n\n"
        f"<b>Benefits:</b>\n"
        f"- Unlimited daily opportunity views\n"
        f"- Priority notifications for new scholarships\n"
        f"- Advanced keyword search\n"
        f"- Full details with eligibility & benefits\n"
        f"- Direct application links\n\n"
        f"To upgrade, contact the admin for manual activation.\n"
        f"(Payment integration coming soon)",
        parse_mode="HTML",
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_count = get_user_count()
    from services.database import get_conn
    conn = get_conn()
    opp_count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    cat_counts = conn.execute(
        "SELECT category, COUNT(*) FROM opportunities GROUP BY category"
    ).fetchall()
    conn.close()

    stats = f"<b>Bot Stats:</b>\n\n"
    stats += f"Total users: {user_count}\n"
    stats += f"Opportunities tracked: {opp_count}\n"
    stats += f"Update frequency: Every hour\n\n"
    stats += f"<b>By Category:</b>\n"
    for row in cat_counts:
        label = CATEGORY_LABELS.get(row[0], row[0])
        stats += f"- {label}: {row[1]}\n"

    await update.message.reply_text(stats, parse_mode="HTML")


async def post_to_channel(app: Application):
    if not TELEGRAM_CHANNEL_ID:
        log.warning("No TELEGRAM_CHANNEL_ID set, skipping channel post")
        return

    opps = get_unsent_opportunities(limit=50)
    bot_info = await app.bot.get_me()

    for opp in opps:
        try:
            text = format_opportunity_full(opp)
            keyboard = [[InlineKeyboardButton(
                "Get More Scholarships!",
                url=f"https://t.me/{bot_info.username}"
            )]]
            await send_full_message(
                app.bot, TELEGRAM_CHANNEL_ID, text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            mark_sent(opp["uid"])
        except Exception as e:
            log.error("Failed to post to channel: %s", e)


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("browse", cmd_browse))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("scholarships", cmd_scholarships))
    app.add_handler(CommandHandler("grants", cmd_grants))
    app.add_handler(CommandHandler("nonprofit", cmd_nonprofit))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("premium", cmd_premium))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(callback_category, pattern=r"^cat:"))
    return app
