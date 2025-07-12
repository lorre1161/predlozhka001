import logging
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler
)
import asyncio
import telegram.error

# Настройки бота
TOKEN = '7754710395:AAGQbOYfDHpdNEEHlFUCQZy806aVKIPSHGY'
CHANNEL_ID = '@market_nft_prm'
MODERATOR_CHAT_ID = -1002853155981  # Проверьте с помощью /get_chat_id
SUPER_ADMINS = {541867942, 7774253158}
MODERATORS = {}

# Состояния ConversationHandler
(
    SELECT_ACTION,
    ADD_MODERATOR,
    REMOVE_MODERATOR,
    REJECT_REASON,
    WAITING_FOR_SUGGESTION
) = range(5)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

suggestions = {}
waiting_for_suggestion = {}
media_group_suggestions = {}  # Для хранения альбомов по media_group_id
pending_media_groups = {}  # Для временного хранения фото альбома

def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMINS

def is_moderator(user_id: int) -> bool:
    return is_super_admin(user_id) or user_id in MODERATORS

async def retry_async(func, *args, retries=3, delay=1, **kwargs):
    """Повторные попытки выполнения асинхронной функции при таймаутах."""
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except telegram.error.TimedOut as e:
            logger.warning(f"Попытка {attempt + 1}/{retries} не удалась: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
            else:
                raise
        except Exception as e:
            logger.error(f"Ошибка в retry_async: {e}")
            raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    if is_super_admin(user.id):
        MODERATORS[user.id] = user.username or f"User_{user.id}"

    keyboard = [
        [InlineKeyboardButton("💡 Предложить", callback_data='suggest')]
    ]

    if is_moderator(user.id):
        keyboard.append([InlineKeyboardButton("👥 Управление модераторами", callback_data='manage_mods')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.callback_query:
            await retry_async(
                update.callback_query.edit_message_text,
                text=f'Главное меню. Привет, {user.first_name}!',
                reply_markup=reply_markup
            )
        else:
            await retry_async(
                update.message.reply_text,
                text=f'Главное меню. Привет, {user.first_name}!',
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        await retry_async(
            update.effective_chat.send_message,
            text=f"❌ Ошибка: {e}"
        )
    return ConversationHandler.END

async def check_bot_rights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для проверки прав бота в чате модераторов."""
    try:
        bot_member = await retry_async(
            context.bot.get_chat_member,
            chat_id=MODERATOR_CHAT_ID,
            user_id=context.bot.id
        )
        if bot_member.status != 'administrator':
            raise ValueError("Бот не является администратором")
        rights = {
            'status': bot_member.status,
            'can_post_messages': getattr(bot_member, 'can_post_messages', False),
            'can_delete_messages': getattr(bot_member, 'can_delete_messages', False)
        }
        await retry_async(
            update.message.reply_text,
            text=f"Права бота в чате {MODERATOR_CHAT_ID}:\n"
                 f"Статус: {rights['status']}\n"
                 f"Может отправлять сообщения: {rights['can_post_messages']}\n"
                 f"Может удалять сообщения: {rights['can_delete_messages']}"
        )
    except Exception as e:
        logger.error(f"Ошибка при проверке прав бота: {e}")
        await retry_async(
            update.message.reply_text,
            text=f"❌ Ошибка при проверке прав бота: {e}. Убедитесь, что бот добавлен в чат {MODERATOR_CHAT_ID} как администратор."
        )

async def check_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для проверки текущего webhook."""
    try:
        webhook_info = await retry_async(context.bot.get_webhook_info)
        await retry_async(
            update.message.reply_text,
            text=f"Webhook info: {webhook_info}"
        )
    except Exception as e:
        logger.error(f"Ошибка при проверке webhook: {e}")
        await retry_async(
            update.message.reply_text,
            text=f"❌ Ошибка при проверке webhook: {e}"
        )

async def delete_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для удаления webhook и переключения на polling."""
    try:
        await retry_async(
            context.bot.delete_webhook,
            drop_pending_updates=True
        )
        await retry_async(
            update.message.reply_text,
            text="Webhook удален. Бот работает в режиме polling."
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении webhook: {e}")
        await retry_async(
            update.message.reply_text,
            text=f"❌ Ошибка при удалении webhook: {e}"
        )

async def request_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в request_suggestion: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    user_id = query.from_user.id
    waiting_for_suggestion[user_id] = True

    try:
        await retry_async(
            query.edit_message_text,
            text="📤 Отправьте ваше предложение (текст, фото или документ):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отменить", callback_data='cancel_suggestion')]
            ])
        )
        return WAITING_FOR_SUGGESTION
    except Exception as e:
        logger.error(f"Ошибка в request_suggestion: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

async def handle_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    if user.id not in waiting_for_suggestion:
        await retry_async(
            update.message.reply_text,
            text="Пожалуйста, сначала нажмите кнопку '💡 Предложить' в главном меню."
        )
        return ConversationHandler.END

    message = update.message
    media_group_id = message.media_group_id

    # Если это альбом, собираем все фото
    if media_group_id:
        if media_group_id not in pending_media_groups:
            pending_media_groups[media_group_id] = {
                'photos': [],
                'caption': message.caption,
                'timestamp': asyncio.get_event_loop().time()
            }
        if message.photo:
            pending_media_groups[media_group_id]['photos'].append(message.photo[-1])
            logger.info(f"Добавлено фото в альбом media_group_id: {media_group_id}, File ID: {message.photo[-1].file_id}")

        # Ждем 1 секунду, чтобы собрать все фото альбома
        if asyncio.get_event_loop().time() - pending_media_groups[media_group_id]['timestamp'] < 1:
            return WAITING_FOR_SUGGESTION

        # Обрабатываем альбом
        suggestion_id = str(media_group_id)
        photo_group = list({photo.file_id: photo for photo in pending_media_groups[media_group_id]['photos']}.values())
        caption = pending_media_groups[media_group_id]['caption']
        del pending_media_groups[media_group_id]
    else:
        suggestion_id = str(message.message_id)
        photo_group = [message.photo[-1]] if message.photo else []
        caption = message.caption if message.caption else message.text if message.text else "Без описания"

    if media_group_id and suggestion_id in media_group_suggestions:
        logger.info(f"Получено дополнительное обновление для альбома media_group_id: {media_group_id}, игнорируем")
        return WAITING_FOR_SUGGESTION

    logger.info(f"Получено предложение {suggestion_id}. Количество фото: {len(photo_group)}, Media group ID: {media_group_id}, File IDs: {[photo.file_id for photo in photo_group]}")

    suggestions[suggestion_id] = {
        'original_message': message,
        'user_id': user.id,
        'username': user.username or f"User_{user.id}",
        'name': user.full_name,
        'moderation_message_id': None,
        'photo_group': photo_group,
        'document': message.document if message.document else None,
        'moderation_messages': [],
        'buttons_message_id': None,
        'reject_request_message_id': None,
        'media_group_id': media_group_id
    }

    if media_group_id:
        media_group_suggestions[media_group_id] = suggestion_id

    text = f"Новое предложение для публикации (ID: {suggestion_id}):\n\n{caption or 'Без описания'}\n\nОт: {user.full_name} (@{user.username or 'NoUsername'})"

    # Проверка прав бота
    try:
        bot_member = await retry_async(
            context.bot.get_chat_member,
            chat_id=MODERATOR_CHAT_ID,
            user_id=context.bot.id
        )
        if bot_member.status != 'administrator':
            logger.error(f"Бот не является администратором в чате {MODERATOR_CHAT_ID}")
            await retry_async(
                update.message.reply_text,
                text="❌ Бот не является администратором в чате модераторов. Пожалуйста, назначьте права администратора."
            )
            if suggestion_id in suggestions:
                del suggestions[suggestion_id]
            if media_group_id and media_group_id in media_group_suggestions:
                del media_group_suggestions[media_group_id]
            return ConversationHandler.END
        logger.info(f"Проверка прав бота пройдена: status={bot_member.status}")
    except Exception as e:
        logger.error(f"Ошибка при проверке прав бота в чате {MODERATOR_CHAT_ID}: {e}")
        await retry_async(
            update.message.reply_text,
            text=f"⚠️ Не удалось проверить права бота: {e}. Продолжаем отправку, предполагая, что бот является администратором."
        )

    logger.info(f"Начинаем отправку предложения {suggestion_id} в чат {MODERATOR_CHAT_ID}")

    # Подготовка клавиатуры
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data=f'approve_{suggestion_id}')],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f'reject_{suggestion_id}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    sent_messages = []  # Для хранения ID отправленных сообщений
    try:
        # Если есть media_group_id и несколько уникальных фото
        if media_group_id and photo_group:
            logger.info(f"Отправка альбома с media_group_id {suggestion_id}. Количество фото: {len(photo_group)}")
            media_group = []
            unique_file_ids = set()
            for idx, photo in enumerate(photo_group[:10]):  # Ограничение в 10 фото
                if photo.file_id not in unique_file_ids:
                    media_group.append(InputMediaPhoto(
                        media=photo.file_id,
                        caption=text if idx == 0 else None
                    ))
                    unique_file_ids.add(photo.file_id)

            if not media_group:
                logger.error(f"Нет уникальных фото для альбома {suggestion_id}")
                await retry_async(
                    update.message.reply_text,
                    text="❌ Ошибка: Не удалось обработать фотографии в альбоме."
                )
                if suggestion_id in suggestions:
                    del suggestions[suggestion_id]
                if media_group_id and media_group_id in media_group_suggestions:
                    del media_group_suggestions[media_group_id]
                return ConversationHandler.END

            sent_messages = await retry_async(
                context.bot.send_media_group,
                chat_id=MODERATOR_CHAT_ID,
                media=media_group
            )
            suggestions[suggestion_id]['moderation_messages'] = [m.message_id for m in sent_messages]
            suggestions[suggestion_id]['moderation_message_id'] = sent_messages[0].message_id

            logger.info(f"Альбом отправлен. Message IDs: {suggestions[suggestion_id]['moderation_messages']}")

            # Отправляем кнопки одним сообщением
            sent_msg = await retry_async(
                context.bot.send_message,
                chat_id=MODERATOR_CHAT_ID,
                text=f"Действия для предложения (ID: {suggestion_id}):",
                reply_to_message_id=sent_messages[0].message_id,
                reply_markup=reply_markup
            )
            suggestions[suggestion_id]['buttons_message_id'] = sent_msg.message_id
            suggestions[suggestion_id]['moderation_messages'].append(sent_msg.message_id)

        # Если одно фото
        elif photo_group:
            logger.info("Отправка одного фото")
            sent_msg = await retry_async(
                context.bot.send_photo,
                chat_id=MODERATOR_CHAT_ID,
                photo=photo_group[-1].file_id,
                caption=text,
                reply_markup=reply_markup
            )
            suggestions[suggestion_id]['moderation_message_id'] = sent_msg.message_id
            suggestions[suggestion_id]['moderation_messages'] = [sent_msg.message_id]
            suggestions[suggestion_id]['buttons_message_id'] = sent_msg.message_id

            logger.info(f"Одно фото отправлено. Message ID: {sent_msg.message_id}")

        # Если документ
        elif suggestions[suggestion_id].get('document'):
            logger.info("Отправка документа")
            sent_msg = await retry_async(
                context.bot.send_document,
                chat_id=MODERATOR_CHAT_ID,
                document=suggestions[suggestion_id]['document'].file_id,
                caption=text,
                reply_markup=reply_markup
            )
            suggestions[suggestion_id]['moderation_message_id'] = sent_msg.message_id
            suggestions[suggestion_id]['moderation_messages'] = [sent_msg.message_id]
            suggestions[suggestion_id]['buttons_message_id'] = sent_msg.message_id

            logger.info(f"Документ отправлен. Message ID: {sent_msg.message_id}")

        # Только текст
        else:
            logger.info("Отправка текста")
            sent_msg = await retry_async(
                context.bot.send_message,
                chat_id=MODERATOR_CHAT_ID,
                text=text,
                reply_markup=reply_markup
            )
            suggestions[suggestion_id]['moderation_message_id'] = sent_msg.message_id
            suggestions[suggestion_id]['moderation_messages'] = [sent_msg.message_id]
            suggestions[suggestion_id]['buttons_message_id'] = sent_msg.message_id

            logger.info(f"Текст отправлен. Message ID: {sent_msg.message_id}")

        logger.info(f"Предложение {suggestion_id} успешно отправлено. Moderation messages: {suggestions[suggestion_id]['moderation_messages']}")

        # Уведомляем пользователя
        if user.id in waiting_for_suggestion:
            del waiting_for_suggestion[user.id]

        await retry_async(
            update.message.reply_text,
            text='✅ Ваше предложение отправлено на модерацию!',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )
        return WAITING_FOR_SUGGESTION

    except Exception as e:
        logger.error(f"Ошибка при отправке предложения {suggestion_id} в чат {MODERATOR_CHAT_ID}: {e}")
        await retry_async(
            update.message.reply_text,
            text=f"❌ Ошибка при отправке предложения: {e}."
        )
        if suggestion_id in suggestions:
            if suggestions[suggestion_id].get('media_group_id') in media_group_suggestions:
                del media_group_suggestions[suggestions[suggestion_id]['media_group_id']]
            del suggestions[suggestion_id]
        return ConversationHandler.END

async def cancel_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в cancel_suggestion: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    user_id = query.from_user.id
    if user_id in waiting_for_suggestion:
        del waiting_for_suggestion[user_id]

    try:
        await retry_async(
            query.edit_message_text,
            text="❌ Создание предложения отменено.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в cancel_suggestion: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
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

    try:
        if hasattr(update, 'message') and update.message:
            await retry_async(
                update.message.reply_text,
                text='🏠 Главное меню:',
                reply_markup=reply_markup
            )
        else:
            await retry_async(
                update.callback_query.edit_message_text,
                text='🏠 Главное меню:',
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка в show_main_menu: {e}")
        await retry_async(
            update.effective_chat.send_message,
            text=f"❌ Ошибка: {e}"
        )

async def manage_moderators(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в manage_moderators: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    user = query.from_user

    if not is_super_admin(user.id):
        await retry_async(
            query.message.reply_text,
            text="❌ Только суперадмины могут управлять модераторами!"
        )
        return await start(update, context)

    keyboard = [
        [InlineKeyboardButton("➕ Добавить модератора", callback_data='add_mod')],
        [InlineKeyboardButton("➖ Удалить модератора", callback_data='remove_mod')],
        [InlineKeyboardButton("📋 Список модераторов", callback_data='list_mods')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await retry_async(
            query.edit_message_text,
            text="👥 Управление модераторами:",
            reply_markup=reply_markup
        )
        return SELECT_ACTION
    except Exception as e:
        logger.error(f"Ошибка в manage_moderators: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

async def list_moderators(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в list_moderators: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    mods_list = "\n".join(
        [f"@{username} (ID: {user_id})" for user_id, username in MODERATORS.items()]) or "Нет модераторов"

    keyboard = [
        [InlineKeyboardButton("🔙 Управление модераторами", callback_data='manage_mods')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await retry_async(
            query.edit_message_text,
            text=f"📋 Текущие модераторы:\n\n{mods_list}",
            reply_markup=reply_markup
        )
        return SELECT_ACTION
    except Exception as e:
        logger.error(f"Ошибка в list_moderators: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

async def add_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в add_moderator: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🔙 Управление модераторами", callback_data='manage_mods')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await retry_async(
            query.edit_message_text,
            text="Введите Telegram ID нового модератора:",
            reply_markup=reply_markup
        )
        return ADD_MODERATOR
    except Exception as e:
        logger.error(f"Ошибка в add_moderator: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

async def handle_add_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await retry_async(
            update.message.reply_text,
            text="❌ Неверный формат ID. Введите числовой Telegram ID."
        )
        return ADD_MODERATOR

    if user_id in MODERATORS:
        await retry_async(
            update.message.reply_text,
            text=f"Пользователь с ID {user_id} уже является модератором!"
        )
    elif user_id in SUPER_ADMINS:
        await retry_async(
            update.message.reply_text,
            text=f"Пользователь с ID {user_id} - суперадмин и так имеет все права!"
        )
    else:
        try:
            user = await retry_async(
                context.bot.get_chat,
                chat_id=user_id
            )
            MODERATORS[user_id] = user.username or f"User_{user_id}"
            await retry_async(
                update.message.reply_text,
                text=f"✅ Пользователь @{user.username or 'NoUsername'} (ID: {user_id}) добавлен в модераторы!"
            )
            await retry_async(
                context.bot.send_message,
                chat_id=user_id,
                text="🎉 Вас назначили модератором! Теперь вы можете модерировать предложения в приватном чате модерации."
            )
        except Exception as e:
            await retry_async(
                update.message.reply_text,
                text=f"❌ Не удалось добавить пользователя с ID {user_id}: {e}"
            )

    return await manage_moderators(update, context)

async def remove_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в remove_moderator: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    if not MODERATORS:
        await retry_async(
            query.edit_message_text,
            text="Нет модераторов для удаления!"
        )
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

    try:
        await retry_async(
            query.edit_message_text,
            text="Выберите модератора для удаления:",
            reply_markup=reply_markup
        )
        return REMOVE_MODERATOR
    except Exception as e:
        logger.error(f"Ошибка в remove_moderator: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

async def handle_remove_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в handle_remove_moderator: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    try:
        _, user_id = query.data.split('_')
        user_id = int(user_id)
    except ValueError:
        logger.error(f"Неверный формат callback_data: {query.data}")
        await retry_async(
            query.message.reply_text,
            text="❌ Ошибка: Неверный формат данных."
        )
        return ConversationHandler.END

    if user_id in MODERATORS and not is_super_admin(user_id):
        username = MODERATORS[user_id]
        del MODERATORS[user_id]
        await retry_async(
            query.edit_message_text,
            text=f"✅ @{username} (ID: {user_id}) больше не модератор!"
        )
        try:
            await retry_async(
                context.bot.send_message,
                chat_id=user_id,
                text="ℹ️ Ваши права модератора были отозваны."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить бывшего модератора: {e}")
    else:
        await retry_async(
            query.edit_message_text,
            text="Модератор не найден или нельзя удалить суперадмина!"
        )

    return await manage_moderators(update, context)

async def request_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в request_reject_reason: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    try:
        _, suggestion_id = query.data.split('_')
        suggestion_id = str(suggestion_id)  # Приводим к строке для консистентности
    except ValueError:
        logger.error(f"Неверный формат callback_data: {query.data}")
        await retry_async(
            query.message.reply_text,
            text="❌ Ошибка: Неверный формат данных."
        )
        return ConversationHandler.END

    logger.info(f"Попытка отклонить предложение {suggestion_id}. Содержимое suggestions: {list(suggestions.keys())}")

    if suggestion_id not in suggestions:
        await retry_async(
            query.message.reply_text,
            text="❌ Предложение не найдено или уже обработано.",
            reply_to_message_id=query.message.message_id
        )
        if suggestion_id in suggestions and suggestions[suggestion_id].get('buttons_message_id'):
            try:
                await retry_async(
                    context.bot.delete_message,
                    chat_id=MODERATOR_CHAT_ID,
                    message_id=suggestions[suggestion_id]['buttons_message_id']
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение с кнопками {suggestions[suggestion_id]['buttons_message_id']}: {e}")
        return ConversationHandler.END

    if not is_moderator(query.from_user.id):
        await retry_async(
            query.message.reply_text,
            text="❌ У вас нет прав для модерации предложений!"
        )
        return ConversationHandler.END

    context.user_data['rejecting'] = {
        'suggestion_id': suggestion_id,
        'moderator_id': query.from_user.id,
        'moderation_msg_id': query.message.message_id
    }

    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data='cancel_reject')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        sent_msg = await retry_async(
            query.message.reply_text,
            text=f"📝 Ответьте на это сообщение, указав причину отклонения предложения (ID: {suggestion_id}):",
            reply_to_message_id=query.message.message_id,
            reply_markup=reply_markup
        )
        suggestions[suggestion_id]['reject_request_message_id'] = sent_msg.message_id
        logger.info(f"Сообщение с просьбой указать причину отправлено. ID: {sent_msg.message_id}, Suggestion ID: {suggestion_id}")
    except Exception as e:
        logger.error(f"Ошибка при запросе причины отклонения для предложения {suggestion_id}: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"📝 Ответьте на это сообщение, указав причину отклонения предложения (ID: {suggestion_id}):",
            reply_to_message_id=query.message.message_id,
            reply_markup=reply_markup
        )

    return REJECT_REASON

async def handle_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.reply_to_message:
        await retry_async(
            update.message.reply_text,
            text=f"❌ Пожалуйста, ответьте на сообщение с просьбой указать причину отклонения (ID: {context.user_data.get('rejecting', {}).get('suggestion_id', 'неизвестно')})."
        )
        return REJECT_REASON

    if not update.message.text:
        await retry_async(
            update.message.reply_text,
            text="❌ Пожалуйста, укажите текстовую причину отклонения."
        )
        return REJECT_REASON

    reason = update.message.text.strip()
    reply_msg_id = update.message.reply_to_message.message_id

    suggestion_id = context.user_data.get('rejecting', {}).get('suggestion_id')
    logger.info(f"Обработка отклонения. Reply_msg_id: {reply_msg_id}, Suggestion_id: {suggestion_id}, Suggestions: {list(suggestions.keys())}")

    if not suggestion_id or suggestion_id not in suggestions:
        await retry_async(
            update.message.reply_text,
            text=f"❌ Предложение не найдено или уже обработано (ID: {suggestion_id})."
        )
        if 'rejecting' in context.user_data:
            del context.user_data['rejecting']
        return ConversationHandler.END

    suggestion = suggestions[suggestion_id]
    if reply_msg_id != suggestion.get('reject_request_message_id'):
        await retry_async(
            update.message.reply_text,
            text=f"❌ Пожалуйста, ответьте на сообщение с просьбой указать причину отклонения (ID: {suggestion_id})."
        )
        logger.error(f"Reply_msg_id {reply_msg_id} не соответствует reject_request_message_id {suggestion.get('reject_request_message_id')}")
        return REJECT_REASON

    user_id = suggestion['user_id']
    suggestion_text = suggestion['original_message'].text or suggestion['original_message'].caption or "Без текста"

    try:
        await retry_async(
            context.bot.send_message,
            chat_id=user_id,
            text=f"❌ Ваше предложение (ID: {suggestion_id}) было отклонено модератором.\n\n<b>Причина:</b> {reason}\n\nВы можете отправить новое предложение через главное меню.",
            parse_mode='HTML'
        )
        logger.info(f"Уведомление об отклонении отправлено пользователю {user_id}")

        # Удаляем все сообщения модерации
        for msg_id in suggestion.get('moderation_messages', []):
            try:
                await retry_async(
                    context.bot.delete_message,
                    chat_id=MODERATOR_CHAT_ID,
                    message_id=msg_id
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение {msg_id}: {e}")

        # Удаляем сообщение с просьбой указать причину
        if suggestion.get('reject_request_message_id'):
            try:
                await retry_async(
                    context.bot.delete_message,
                    chat_id=MODERATOR_CHAT_ID,
                    message_id=suggestion['reject_request_message_id']
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение с просьбой причины {suggestion['reject_request_message_id']}: {e}")

        # Удаляем сообщение с причиной
        try:
            await retry_async(update.message.delete)
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение с причиной: {e}")

        await retry_async(
            context.bot.send_message,
            chat_id=MODERATOR_CHAT_ID,
            text=f"❌ Предложение (ID: {suggestion_id}) от @{suggestion['username']} отклонено модератором @{update.effective_user.username or 'NoUsername'}.\n\n<b>Текст предложения:</b> {suggestion_text}\n<b>Причина:</b> {reason}",
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке отклонения предложения {suggestion_id}: {e}")
        await retry_async(
            context.bot.send_message,
            chat_id=MODERATOR_CHAT_ID,
            text=f"❌ Не удалось обработать отклонение предложения (ID: {suggestion_id}): {e}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )
    finally:
        if suggestion_id in suggestions:
            if suggestions[suggestion_id].get('media_group_id') in media_group_suggestions:
                del media_group_suggestions[suggestions[suggestion_id]['media_group_id']]
            del suggestions[suggestion_id]
        if 'rejecting' in context.user_data:
            del context.user_data['rejecting']

    return ConversationHandler.END

async def cancel_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в cancel_reject: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    if 'rejecting' in context.user_data:
        suggestion_id = context.user_data['rejecting'].get('suggestion_id')
        if suggestion_id in suggestions and suggestions[suggestion_id].get('reject_request_message_id'):
            try:
                await retry_async(
                    context.bot.delete_message,
                    chat_id=MODERATOR_CHAT_ID,
                    message_id=suggestions[suggestion_id]['reject_request_message_id']
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение с просьбой причины: {e}")
        del context.user_data['rejecting']

    try:
        await retry_async(
            query.message.reply_text,
            text="❌ Отклонение отменено. Предложение остается на модерации.",
            reply_to_message_id=query.message.message_id
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в cancel_reject: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

async def approve_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в approve_suggestion: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    try:
        _, suggestion_id = query.data.split('_')
        suggestion_id = str(suggestion_id)  # Приводим к строке для консистентности
    except ValueError:
        logger.error(f"Неверный формат callback_data: {query.data}")
        await retry_async(
            query.message.reply_text,
            text="❌ Ошибка: Неверный формат данных."
        )
        return ConversationHandler.END

    logger.info(f"Попытка одобрить предложение {suggestion_id}. Содержимое suggestions: {list(suggestions.keys())}")

    if suggestion_id not in suggestions:
        await retry_async(
            query.message.reply_text,
            text="❌ Предложение не найдено или уже обработано.",
            reply_to_message_id=query.message.message_id
        )
        if suggestion_id in suggestions and suggestions[suggestion_id].get('buttons_message_id'):
            try:
                await retry_async(
                    context.bot.delete_message,
                    chat_id=MODERATOR_CHAT_ID,
                    message_id=suggestions[suggestion_id]['buttons_message_id']
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение с кнопками {suggestions[suggestion_id]['buttons_message_id']}: {e}")
        return ConversationHandler.END

    if not is_moderator(query.from_user.id):
        await retry_async(
            query.message.reply_text,
            text="❌ У вас нет прав для модерации предложений!"
        )
        return ConversationHandler.END

    suggestion = suggestions[suggestion_id]
    message = suggestion['original_message']

    try:
        if suggestion.get('media_group_id') and len(set(photo.file_id for photo in suggestion.get('photo_group', []))) > 1:
            logger.info(f"Публикация альбома для предложения {suggestion_id}. Количество фото: {len(suggestion['photo_group'])}")
            media_group = []
            unique_file_ids = set()
            for idx, photo in enumerate(suggestion['photo_group'][:10]):
                if photo.file_id not in unique_file_ids:
                    media_group.append(InputMediaPhoto(
                        media=photo.file_id,
                        caption=message.caption if idx == 0 and message.caption else None
                    ))
                    unique_file_ids.add(photo.file_id)

            sent_messages = await retry_async(
                context.bot.send_media_group,
                chat_id=CHANNEL_ID,
                media=media_group
            )
            message_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}/{sent_messages[0].message_id}"

        elif suggestion.get('photo_group'):
            logger.info(f"Публикация одного фото для предложения {suggestion_id}")
            sent_message = await retry_async(
                context.bot.send_photo,
                chat_id=CHANNEL_ID,
                photo=suggestion['photo_group'][-1].file_id,
                caption=message.caption if message.caption else None
            )
            message_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}/{sent_message.message_id}"

        elif suggestion.get('document'):
            logger.info(f"Публикация документа для предложения {suggestion_id}")
            sent_message = await retry_async(
                context.bot.send_document,
                chat_id=CHANNEL_ID,
                document=suggestion['document'].file_id,
                caption=message.caption if message.caption else None
            )
            message_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}/{sent_message.message_id}"

        else:
            logger.info(f"Публикация текста для предложения {suggestion_id}")
            sent_message = await retry_async(
                context.bot.send_message,
                chat_id=CHANNEL_ID,
                text=message.text
            )
            message_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}/{sent_message.message_id}"

        try:
            await retry_async(
                context.bot.send_message,
                chat_id=suggestion['user_id'],
                text=f"🎉 Ваше предложение (ID: {suggestion_id}) было опубликовано в канале!\n\nСсылка: {message_link}",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить автора о публикации: {e}")

        # Удаляем сообщения модерации
        for msg_id in suggestion.get('moderation_messages', []):
            try:
                await retry_async(
                    context.bot.delete_message,
                    chat_id=MODERATOR_CHAT_ID,
                    message_id=msg_id
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение {msg_id}: {e}")

        await retry_async(
            query.message.reply_text,
            text=f"✅ Предложение (ID: {suggestion_id}) от @{suggestion['username']} опубликовано в канале!\n\n<b>Ссылка:</b> {message_link}",
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_to_message_id=query.message.message_id,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

        # Удаляем сообщение с кнопками
        if suggestion.get('buttons_message_id'):
            try:
                await retry_async(
                    context.bot.delete_message,
                    chat_id=MODERATOR_CHAT_ID,
                    message_id=suggestion['buttons_message_id']
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение с кнопками {suggestion['buttons_message_id']}: {e}")

    except Exception as e:
        logger.error(f"Ошибка при публикации предложения {suggestion_id}: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Не удалось опубликовать предложение (ID: {suggestion_id}): {e}",
            reply_to_message_id=query.message.message_id,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )
    finally:
        if suggestion_id in suggestions:
            if suggestions[suggestion_id].get('media_group_id') in media_group_suggestions:
                del media_group_suggestions[suggestions[suggestion_id]['media_group_id']]
            del suggestions[suggestion_id]

    return ConversationHandler.END

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await retry_async(
            update.message.reply_text,
            text=f"Chat ID: {update.effective_chat.id}"
        )
    except Exception as e:
        logger.error(f"Ошибка в get_chat_id: {e}")
        await retry_async(
            update.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в button_callback: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

    logger.info(f"Получен callback: {query.data}")

    try:
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
        else:
            logger.error(f"Неизвестный callback_data: {query.data}")
            await retry_async(
                query.message.reply_text,
                text="❌ Неизвестная команда."
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в button_callback для callback_data {query.data}: {e}")
        await retry_async(
            query.message.reply_text,
            text=f"❌ Ошибка: {e}"
        )
        return ConversationHandler.END

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
                CallbackQueryHandler(cancel_suggestion, pattern='^cancel_suggestion$'),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ]
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(start, pattern='^(back_to_main|main_menu)$')
        ]
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("get_chat_id", get_chat_id))
    application.add_handler(CommandHandler("check_bot_rights", check_bot_rights))
    application.add_handler(CommandHandler("check_webhook", check_webhook))
    application.add_handler(CommandHandler("delete_webhook", delete_webhook))

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
