import csv
import logging
import os
from datetime import datetime, UTC
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "").strip()
TABLE_URL = os.getenv("TABLE_URL", "").strip()
VIDEO_URL = os.getenv("VIDEO_URL", "").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", "").strip()
BOT_NAME = os.getenv("BOT_NAME", "Бесплатный автоматический калькулятор юнит-экономики WB").strip()
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "").strip()

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
LEADS_CSV = DATA_DIR / "leads.csv"

WAIT_SUB_CHECK = 0


def ensure_csv_headers() -> None:
    if not LEADS_CSV.exists():
        with LEADS_CSV.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "created_at",
                "telegram_user_id",
                "username",
                "first_name",
                "last_name",
                "is_subscribed",
                "received_calculator",
                "wants_audit",
                "audit_text",
            ])


def save_or_update_lead(
    user_data: dict,
    is_subscribed: str = "",
    received_calculator: str = "",
    wants_audit: str = "",
    audit_text: str = "",
) -> None:
    ensure_csv_headers()

    rows = []
    found = False

    with LEADS_CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("telegram_user_id", "")) == str(user_data.get("telegram_user_id", "")):
                if is_subscribed:
                    row["is_subscribed"] = is_subscribed
                if received_calculator:
                    row["received_calculator"] = received_calculator
                if wants_audit:
                    row["wants_audit"] = wants_audit
                if audit_text:
                    row["audit_text"] = audit_text
                found = True
            rows.append(row)

    if not found:
        rows.append({
            "created_at": datetime.now(UTC).isoformat(),
            "telegram_user_id": str(user_data.get("telegram_user_id", "")),
            "username": user_data.get("username", ""),
            "first_name": user_data.get("first_name", ""),
            "last_name": user_data.get("last_name", ""),
            "is_subscribed": is_subscribed or "",
            "received_calculator": received_calculator or "",
            "wants_audit": wants_audit or "",
            "audit_text": audit_text or "",
        })

    with LEADS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "created_at",
                "telegram_user_id",
                "username",
                "first_name",
                "last_name",
                "is_subscribed",
                "received_calculator",
                "wants_audit",
                "audit_text",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def start_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["Получить калькулятор"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Подписаться на канал", url=CHANNEL_URL)],
        [InlineKeyboardButton("Подписался, проверить", callback_data="check_sub")],
    ])


def result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Открыть калькулятор", url=TABLE_URL)],
        [InlineKeyboardButton("Смотреть видеоинструкцию", url=VIDEO_URL)],
        [InlineKeyboardButton("Перейти в канал", url=CHANNEL_URL)],
        [InlineKeyboardButton("Хочу разбор", callback_data="want_audit")],
    ])


async def is_user_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.exception("Subscription check failed: %s", e)
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    context.user_data.clear()
    context.user_data["telegram_user_id"] = user.id
    context.user_data["username"] = user.username or ""
    context.user_data["first_name"] = user.first_name or ""
    context.user_data["last_name"] = user.last_name or ""
    context.user_data["awaiting_audit"] = False

    save_or_update_lead(context.user_data)

    await update.message.reply_text(
        "Нажми кнопку ниже, чтобы получить калькулятор.",
        reply_markup=start_keyboard(),
    )
    return WAIT_SUB_CHECK


async def handle_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["awaiting_audit"] = False

    await update.message.reply_text(
        "Привет.\n\n"
        "Чтобы получить калькулятор, подпишись на мой канал.\n"
        "После проверки я сразу пришлю тебе калькулятор и видеоинструкцию.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await update.message.reply_text(
        "Шаг 1. Подпишись на канал и потом нажми «Подписался, проверить».",
        reply_markup=subscription_keyboard(),
    )
    return WAIT_SUB_CHECK


async def handle_check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    subscribed = await is_user_subscribed(context, user_id)

    if not subscribed:
        await query.message.reply_text(
            f"Я пока не вижу подписку на канал {CHANNEL_USERNAME}.\n\n"
            "Подпишись и нажми «Подписался, проверить» ещё раз.",
            reply_markup=subscription_keyboard(),
        )
        return WAIT_SUB_CHECK

    user_data = {
        "telegram_user_id": query.from_user.id,
        "username": query.from_user.username or "",
        "first_name": query.from_user.first_name or "",
        "last_name": query.from_user.last_name or "",
    }

    save_or_update_lead(
        user_data,
        is_subscribed="yes",
        received_calculator="yes",
    )

    await query.message.reply_text(
        "Готово. Ниже всё, что тебе нужно:\n\n"
        "1. Калькулятор\n"
        "2. Видеоинструкция\n"
        "3. Канал с разбором логики\n\n"
        "Сначала открой видеоинструкцию, потом сделай копию таблицы и подставь свои данные."
    )

    await query.message.reply_text(
        "Выбери следующий шаг:",
        reply_markup=result_keyboard(),
    )

    return ConversationHandler.END


async def handle_want_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_data = {
        "telegram_user_id": query.from_user.id,
        "username": query.from_user.username or "",
        "first_name": query.from_user.first_name or "",
        "last_name": query.from_user.last_name or "",
    }

    context.user_data.update(user_data)
    context.user_data["awaiting_audit"] = True

    save_or_update_lead(user_data, wants_audit="yes")

    await query.message.reply_text(
        "Заявка на разбор.\n\n"
        "Ответь одним сообщением по шаблону:\n\n"
        "1. Ниша\n"
        "2. Оборот\n"
        "3. Сколько SKU\n"
        "4. Главная проблема"
    )


async def handle_audit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_audit"):
        return

    audit_text = (update.message.text or "").strip()
    user = update.effective_user

    user_data = {
        "telegram_user_id": user.id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
    }

    save_or_update_lead(
        user_data,
        wants_audit="yes",
        audit_text=audit_text,
    )

    context.user_data["awaiting_audit"] = False

    await update.message.reply_text(
        "Спасибо. Заявку получил.\n\n"
        "Я посмотрю её и свяжусь с тобой в Telegram."
    )

    if OWNER_CHAT_ID:
        username = f"@{user.username}" if user.username else "—"
        text = (
            "Новая заявка на разбор:\n\n"
            f"Имя: {(user.first_name or '')} {(user.last_name or '')}".strip() + "\n"
            f"Username: {username}\n"
            f"TG ID: {user.id}\n\n"
            "Ответ клиента:\n"
            f"{audit_text}"
        )
        await context.bot.send_message(chat_id=OWNER_CHAT_ID, text=text)


async def inline_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        if query.data == "check_sub":
            await handle_check_subscription(update, context)
            return
    except Exception as e:
        logger.exception("inline_actions failed: %s", e)
        await query.message.reply_text(
            "Что-то сломалось. Нажми /start и попробуй ещё раз."
        )


async def export_leads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not OWNER_CHAT_ID or str(update.effective_chat.id) != OWNER_CHAT_ID:
        await update.message.reply_text("Нет доступа.")
        return

    ensure_csv_headers()
    await update.message.reply_document(document=LEADS_CSV.open("rb"))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Логика простая:\n"
        "1. Нажимаешь «Получить калькулятор»\n"
        "2. Подписываешься на канал\n"
        "3. Нажимаешь «Подписался, проверить»\n"
        "4. Получаешь калькулятор и видеоинструкцию\n\n"
        "Если нажимаешь «Хочу разбор», потом нужно одним сообщением ответить на 4 пункта."
    )


async def get_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await start(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["awaiting_audit"] = False
    await update.message.reply_text(
        "Остановили. Чтобы начать заново, нажми /start",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception: %s", context.error)


def validate_env() -> None:
    missing = []
    for name, value in [
        ("BOT_TOKEN", BOT_TOKEN),
        ("CHANNEL_USERNAME", CHANNEL_USERNAME),
        ("TABLE_URL", TABLE_URL),
        ("VIDEO_URL", VIDEO_URL),
        ("CHANNEL_URL", CHANNEL_URL),
    ]:
        if not value:
            missing.append(name)

    if missing:
        raise RuntimeError("Не заполнены переменные окружения: " + ", ".join(missing))


def main() -> None:
    validate_env()
    ensure_csv_headers()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("get", get_cmd),
            MessageHandler(filters.Regex("^Получить калькулятор$"), handle_start_button),
        ],
        states={
            WAIT_SUB_CHECK: [
                MessageHandler(filters.Regex("^Получить калькулятор$"), handle_start_button),
                CallbackQueryHandler(handle_check_subscription, pattern="^check_sub$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_want_audit, pattern="^want_audit$"))
    app.add_handler(CallbackQueryHandler(inline_actions, pattern="^check_sub$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_audit_text))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("export_leads", export_leads))
    app.add_error_handler(error_handler)

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
