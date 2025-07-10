import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler
)

# Настройки бота
TOKEN = '7754710395:AAGQbOYfDHpdNEEHlFUCQZy806aVKIPSHGY'
CHANNEL_ID = '@market_nft_prm'
MODERATOR_CHAT_ID = '@moderation_predlozhka1'  # Чат модераторов
SUPER_ADMINS = {541867942, 7774253158}  # Суперадмины по Telegram ID
MODERATORS = {}  # {user_id: username}

# Состояния ConversationHandler
(
    SELECT_ACTION,
    ADD_MODERATOR,
    REMOVE_MODERATOR,
    REJECT_REASON,
    WAITING_FOR_SUGGESTION  # Новое состояние для ожидания предложения
) = range(5)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

suggestions = {}
waiting_for_suggestion = {}  # Словарь для отслеживания пользователей, ожидающих предложение


def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMINS


def is_moderator(user_id: int) -> bool:
    return is_super_admin(user_id) or user_id in MODERATORS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    if is_super_admin(user.id):
        MODERATORS[user.id] = user.username

    keyboard = [
        [InlineKeyboardButton("💡 Предложить", callback_data='suggest')]
    ]

    if is_moderator(user.id):
        keyboard.append([InlineKeyboardButton("👥 Управление модераторами", callback_data='manage_mods')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            f'Главное меню. Привет, {user.first_name}!',
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            f'Главное меню. Привет, {user.first_name}!',
            reply_markup=reply_markup
        )
    return ConversationHandler.END


async def request_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    waiting_for_suggestion[user_id] = True  # Помечаем, что ожидаем предложение от этого пользователя

    await query.edit_message_text(
        "📤 Отправьте ваше предложение (текст, фото или документ):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отменить", callback_data='cancel_suggestion')]
        ])
    )
    return WAITING_FOR_SUGGESTION


async def handle_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    # Проверяем, что пользователь действительно нажал кнопку "Предложить"
    if user.id not in waiting_for_suggestion:
        await update.message.reply_text("Пожалуйста, сначала нажмите кнопку '💡 Предложить' в главном меню.")
        return ConversationHandler.END

    message = update.message
    suggestion_id = message.message_id
    suggestions[suggestion_id] = {
        'original_message': message,
        'user_id': user.id,
        'username': user.username,
        'name': user.full_name,
        'moderation_message_id': None
    }

    caption = message.caption if message.caption else message.text if message.text else "Фото без описания"
    text = f"Новое предложение для публикации (ID: {suggestion_id}):\n\n{caption}\n\nОт: {user.full_name} (@{user.username})"

    try:
        keyboard = [
            [InlineKeyboardButton("✅ Опубликовать", callback_data=f'approve_{suggestion_id}')],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f'reject_{suggestion_id}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if message.photo:
            sent_msg = await context.bot.send_photo(
                chat_id=MODERATOR_CHAT_ID,
                photo=message.photo[-1].file_id,
                caption=text,
                reply_markup=reply_markup
            )
        elif message.document:
            sent_msg = await context.bot.send_document(
                chat_id=MODERATOR_CHAT_ID,
                document=message.document.file_id,
                caption=text,
                reply_markup=reply_markup
            )
        else:
            sent_msg = await context.bot.send_message(
                chat_id=MODERATOR_CHAT_ID,
                text=text,
                reply_markup=reply_markup
            )

        suggestions[suggestion_id]['moderation_message_id'] = sent_msg.message_id
        logger.info(f"Предложение {suggestion_id} отправлено в чат модераторов {MODERATOR_CHAT_ID}")

        # Удаляем пользователя из ожидающих предложение
        if user.id in waiting_for_suggestion:
            del waiting_for_suggestion[user.id]

        await update.message.reply_text('✅ Ваше предложение отправлено на модерацию!')
        return await show_main_menu(update, context)

    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в чат модераторов {MODERATOR_CHAT_ID}: {e}")
        await update.message.reply_text("❌ Ошибка при отправке предложения в чат модераторов.")
        return ConversationHandler.END


async def cancel_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id in waiting_for_suggestion:
        del waiting_for_suggestion[user_id]

    await query.edit_message_text(
        "❌ Создание предложения отменено.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
        ])
    )
    return ConversationHandler.END


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    keyboard = [
        [InlineKeyboardButton("💡 Предложить", callback_data='suggest')]
    ]

    if is_moderator(user.id):
        keyboard.append([InlineKeyboardButton("👥 Управление модераторами", callback_data='manage_mods')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(
            '🏠 Главное меню:',
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.edit_message_text(
            '🏠 Главное меню:',
            reply_markup=reply_markup
        )


async def manage_moderators(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not is_super_admin(user.id):
        await query.edit_message_text("❌ Только суперадмины могут управлять модераторами!")
        return await start(update, context)

    keyboard = [
        [InlineKeyboardButton("➕ Добавить модератора", callback_data='add_mod')],
        [InlineKeyboardButton("➖ Удалить модератора", callback_data='remove_mod')],
        [InlineKeyboardButton("📋 Список модераторов", callback_data='list_mods')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "👥 Управление модераторами:",
        reply_markup=reply_markup
    )
    return SELECT_ACTION


async def list_moderators(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    mods_list = "\n".join(
        [f"@{username} (ID: {user_id})" for user_id, username in MODERATORS.items()]) or "Нет модераторов"

    keyboard = [
        [InlineKeyboardButton("🔙 Управление модераторами", callback_data='manage_mods')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"📋 Текущие модераторы:\n\n{mods_list}",
        reply_markup=reply_markup
    )
    return SELECT_ACTION


async def add_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔙 Управление модераторами", callback_data='manage_mods')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Введите Telegram ID нового модератора:",
        reply_markup=reply_markup
    )
    return ADD_MODERATOR


async def handle_add_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите числовой Telegram ID.")
        return ADD_MODERATOR

    if user_id in MODERATORS:
        await update.message.reply_text(f"Пользователь с ID {user_id} уже является модератором!")
    elif user_id in SUPER_ADMINS:
        await update.message.reply_text(f"Пользователь с ID {user_id} - суперадмин и так имеет все права!")
    else:
        try:
            user = await context.bot.get_chat(user_id)
            MODERATORS[user_id] = user.username
            await update.message.reply_text(f"✅ Пользователь @{user.username} (ID: {user_id}) добавлен в модераторы!")
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 Вас назначили модератором! Теперь вы можете модерировать предложения в чате @moderation_predlozhka."
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Не удалось добавить пользователя с ID {user_id}: {e}")

    return await manage_moderators(update, context)


async def remove_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not MODERATORS:
        await query.edit_message_text("Нет модераторов для удаления!")
        return await manage_moderators(update, context)

    keyboard = [
        [InlineKeyboardButton(f"@{username} (ID: {user_id})", callback_data=f'remove_{user_id}')]
        for user_id, username in MODERATORS.items() if not is_super_admin(user_id)
    ]
    keyboard += [
        [InlineKeyboardButton("🔙 Управление модераторами", callback_data='manage_mods')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Выберите модератора для удаления:",
        reply_markup=reply_markup
    )
    return REMOVE_MODERATOR


async def handle_remove_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, user_id = query.data.split('_')
    user_id = int(user_id)

    if user_id in MODERATORS and not is_super_admin(user_id):
        username = MODERATORS[user_id]
        del MODERATORS[user_id]
        await query.edit_message_text(f"✅ @{username} (ID: {user_id}) больше не модератор!")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="ℹ️ Ваши права модератора были отозваны."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить бывшего модератора: {e}")
    else:
        await query.edit_message_text("Модератор не найден или нельзя удалить суперадмина!")

    return await manage_moderators(update, context)


async def request_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, suggestion_id = query.data.split('_')
    suggestion_id = int(suggestion_id)

    if suggestion_id not in suggestions:
        await query.edit_message_text("❌ Предложение не найдено или уже обработано.")
        return ConversationHandler.END

    if not is_moderator(query.from_user.id):
        await query.message.reply_text("❌ У вас нет прав для модерации предложений!")
        return ConversationHandler.END

    context.user_data['rejecting'] = {
        'suggestion_id': suggestion_id,
        'moderator_id': query.from_user.id,
        'moderation_msg_id': query.message.message_id
    }

    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data='cancel_reject')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            f"📝 Ответьте на это сообщение, указав причину отклонения предложения (ID: {suggestion_id}):",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка при запросе причины отклонения: {e}")
        await query.message.reply_text(
            f"📝 Ответьте на это сообщение, указав причину отклонения предложения (ID: {suggestion_id}):",
            reply_markup=reply_markup
        )

    return REJECT_REASON


async def handle_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Пожалуйста, ответьте на сообщение предложения, чтобы указать причину отклонения.")
        return REJECT_REASON

    if not update.message.text:
        await update.message.reply_text("❌ Пожалуйста, укажите текстовую причину отклонения.")
        return REJECT_REASON

    reason = update.message.text.strip()
    reply_msg_id = update.message.reply_to_message.message_id
    suggestion_id = None

    for sug_id, sug_data in suggestions.items():
        if sug_data['moderation_message_id'] == reply_msg_id:
            suggestion_id = sug_id
            break

    if not suggestion_id or suggestion_id not in suggestions:
        await update.message.reply_text("❌ Предложение не найдено или уже обработано.")
        return ConversationHandler.END

    suggestion = suggestions[suggestion_id]
    user_id = suggestion['user_id']

    if not is_moderator(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для модерации предложений!")
        return ConversationHandler.END

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Ваше предложение (ID: {suggestion_id}) было отклонено модератором.\n\n<b>Причина:</b> {reason}\n\nВы можете отправить новое предложение через главное меню.",
            parse_mode='HTML'
        )
        logger.info(f"Уведомление об отклонении отправлено пользователю {user_id}")

        try:
            await context.bot.delete_message(
                chat_id=MODERATOR_CHAT_ID,
                message_id=suggestion['moderation_message_id']
            )
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение в чате модераторов: {e}")

        try:
            await update.message.delete()
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение с причиной: {e}")

        await context.bot.send_message(
            chat_id=MODERATOR_CHAT_ID,
            text=f"✅ Предложение (ID: {suggestion_id}) отклонено модератором @{update.effective_user.username}.\n\n<b>Причина:</b> {reason}",
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке отклонения: {e}")
        await context.bot.send_message(
            chat_id=MODERATOR_CHAT_ID,
            text=f"❌ Не удалось обработать отклонение предложения (ID: {suggestion_id}): {e}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )
    finally:
        if suggestion_id in suggestions:
            del suggestions[suggestion_id]
        if 'rejecting' in context.user_data:
            del context.user_data['rejecting']

    return ConversationHandler.END


async def cancel_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if 'rejecting' in context.user_data:
        del context.user_data['rejecting']

    await query.edit_message_text(
        "❌ Отклонение отменено. Предложение остается на модерации.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
        ])
    )
    return ConversationHandler.END


async def approve_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, suggestion_id = query.data.split('_')
    suggestion_id = int(suggestion_id)

    if suggestion_id not in suggestions:
        await query.edit_message_text("❌ Предложение не найдено или уже обработано.")
        return ConversationHandler.END

    if not is_moderator(query.from_user.id):
        await query.message.reply_text("❌ У вас нет прав для модерации предложений!")
        return ConversationHandler.END

    suggestion = suggestions[suggestion_id]
    message = suggestion['original_message']

    try:
        if message.photo:
            sent_message = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=message.photo[-1].file_id,
                caption=message.caption if message.caption else None
            )
        elif message.document:
            sent_message = await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=message.document.file_id,
                caption=message.caption if message.caption else None
            )
        else:
            sent_message = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=message.text
            )

        message_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}/{sent_message.message_id}"

        try:
            await context.bot.send_message(
                chat_id=suggestion['user_id'],
                text=f"🎉 Ваше предложение (ID: {suggestion_id}) было опубликовано в канале!\n\nСсылка: {message_link}",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить автора о публикации: {e}")

        try:
            await context.bot.delete_message(
                chat_id=MODERATOR_CHAT_ID,
                message_id=suggestion['moderation_message_id']
            )
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение в чате модераторов: {e}")

        await query.edit_message_text(
            f"✅ Предложение (ID: {suggestion_id}) от @{suggestion['username']} опубликовано в канале!\n\nСсылка: {message_link}",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

    except Exception as e:
        logger.error(f"Ошибка при публикации предложения {suggestion_id}: {e}")
        await query.edit_message_text(
            f"❌ Не удалось опубликовать предложение (ID: {suggestion_id})",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )
    finally:
        if suggestion_id in suggestions:
            del suggestions[suggestion_id]

    return ConversationHandler.END


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == 'suggest':
        return await request_suggestion(update, context)
    elif query.data == 'manage_mods':
        return await manage_moderators(update, context)
    elif query.data == 'list_mods':
        return await list_moderators(update, context)
    elif query.data == 'add_mod':
        return await add_moderator(update, context)
    elif query.data == 'remove_mod':
        return await remove_moderator(update, context)
    elif query.data.startswith('remove_'):
        return await handle_remove_moderator(update, context)
    elif query.data.startswith('approve_'):
        return await approve_suggestion(update, context)
    elif query.data.startswith('reject_'):
        return await request_reject_reason(update, context)
    elif query.data in ['cancel_reject', 'cancel_suggestion']:
        return await cancel_reject(update, context) if query.data == 'cancel_reject' else await cancel_suggestion(
            update, context)
    elif query.data in ['back_to_main', 'main_menu']:
        return await start(update, context)


def main() -> None:
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_callback)
        ],
        states={
            SELECT_ACTION: [
                CallbackQueryHandler(manage_moderators, pattern='^manage_mods$'),
                CallbackQueryHandler(list_moderators, pattern='^list_mods$'),
                CallbackQueryHandler(add_moderator, pattern='^add_mod$'),
                CallbackQueryHandler(remove_moderator, pattern='^remove_mod$'),
                CallbackQueryHandler(handle_remove_moderator, pattern='^remove_\d+$'),
                CallbackQueryHandler(start, pattern='^(back_to_main|main_menu)$')
            ],
            ADD_MODERATOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_moderator),
                CallbackQueryHandler(manage_moderators, pattern='^manage_mods$'),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            REMOVE_MODERATOR: [
                CallbackQueryHandler(handle_remove_moderator, pattern='^remove_\d+$'),
                CallbackQueryHandler(manage_moderators, pattern='^manage_mods$'),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            REJECT_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reject_reason),
                CallbackQueryHandler(cancel_reject, pattern='^cancel_reject$')
            ],
            WAITING_FOR_SUGGESTION: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.ATTACHMENT, handle_suggestion),
                CallbackQueryHandler(cancel_suggestion, pattern='^cancel_suggestion$')
            ]
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(start, pattern='^(back_to_main|main_menu)$')
        ]
    )

    application.add_handler(conv_handler)

    # Обработчик для обычных сообщений (не предложек)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda update, context: None
    ))

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == '__main__':
    main()
