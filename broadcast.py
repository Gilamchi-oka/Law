"""
Рассылка Telegram-постов из Избранного (Saved Messages).
Команда: /broadcast [лимит]
  - берёт последнее сообщение из Saved Messages
  - рассылает всем клиентам из clients.json у которых есть номер телефона
  - соблюдает паузы между отправками чтобы не попасть в спам
  - репортит прогресс в отчётный канал
"""
import asyncio
from telethon.tl.types import InputPeerSelf
import storage
import logger

PAUSE_BETWEEN = 35   # секунд между отправками (безопасный интервал)
PAUSE_CHUNK   = 10   # пауза каждые N отправок


async def run_broadcast(client, report_chat_id: int, admin_id: int, limit: int = None):
    """
    1. Берём последнее сообщение из Saved Messages
    2. Рассылаем всем клиентам у которых есть phone в базе
    """
    # Получаем последнее сообщение из Избранного
    saved = await client.get_messages("me", limit=1)
    if not saved or not saved[0]:
        await client.send_message(admin_id, "❌ Избранное пустое — сохрани туда пост с фото и текстом, потом повтори /broadcast")
        return

    post = saved[0]

    clients = storage.all_clients()
    phones = [c["phone"] for c in clients if c.get("phone")]
    if limit:
        phones = phones[:limit]

    total = len(phones)
    await logger.tg(f"📢 Начинаю рассылку в Telegram\nПостов: 1 | Получателей: {total}", "info")
    await client.send_message(admin_id,
        f"📢 Запускаю рассылку\nСообщение: {'фото + текст' if post.photo else 'текст'}\n"
        f"Получателей: {total}\n\nОстановить: /stopbroadcast"
    )

    sent = 0
    failed = 0
    _broadcast_running[0] = True

    for i, phone in enumerate(phones, 1):
        if not _broadcast_running[0]:
            await logger.tg(f"🛑 Рассылка остановлена вручную. Отправлено: {sent}", "warn")
            await client.send_message(admin_id, f"🛑 Рассылка остановлена. Отправлено: {sent}/{total}")
            return

        try:
            # Пытаемся найти пользователя по номеру
            entity = await client.get_input_entity(f"+{phone}")
            await client.forward_messages(entity, post)
            sent += 1
        except Exception as e:
            failed += 1
            err_short = str(e)[:80]
            print(f"[BROADCAST] Не удалось отправить {phone}: {err_short}")

        # Прогресс каждые 25 отправок
        if i % 25 == 0:
            await logger.tg(f"📨 Рассылка: {sent} отправлено, {failed} ошибок, осталось {total - i}", "info")

        # Пауза между отправками
        if i % PAUSE_CHUNK == 0:
            await asyncio.sleep(PAUSE_BETWEEN * 2)
        else:
            await asyncio.sleep(PAUSE_BETWEEN)

    _broadcast_running[0] = False
    await logger.tg(
        f"✅ Рассылка завершена\nОтправлено: {sent}/{total} | Ошибок: {failed}", "info"
    )
    await client.send_message(admin_id,
        f"✅ Рассылка завершена!\nОтправлено: {sent}/{total}\nОшибок: {failed}"
    )


_broadcast_running = [False]
_broadcast_task = [None]


def stop_broadcast():
    _broadcast_running[0] = False


def is_running():
    return _broadcast_running[0]
