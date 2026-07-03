"""
Рассылка Telegram-постов из Избранного (Saved Messages) — по номерам телефонов
из storage.clients.

Устойчивость к рестартам: каждый отправленный номер сразу помечается tg_sent=1
в БД (storage.mark_tg_client_sent). Если процесс упадёт/передеплоится —
следующий /broadcast продолжит со следующего ещё не отправленного номера,
без повторной отправки уже отправленным.

Недельный лимит (WEEKLY_LIMIT, по умолчанию 1000) считается скользящим окном
за последние 7 дней (storage.tg_broadcast_sent_in_last_days), а не по
календарной неделе — так рестарт посреди недели не сбрасывает и не обходит лимит.

Команда /broadcast [N] — если указать N, разошлёт максимум N штук за этот запуск
(удобно для тестовой пачки 50-100 перед тем как катить на всю базу),
но всё равно не выйдет за пределы недельного лимита.
"""
import asyncio
import os

import storage
import logger

PAUSE_BETWEEN = float(os.environ.get("TG_PAUSE_SECONDS", "35"))   # секунд между отправками
PAUSE_CHUNK = int(os.environ.get("TG_PAUSE_CHUNK", "10"))          # доп. пауза каждые N отправок
PAUSE_CHUNK_EXTRA = float(os.environ.get("TG_PAUSE_CHUNK_EXTRA", "35"))
WEEKLY_LIMIT = int(os.environ.get("TG_WEEKLY_LIMIT", "1000"))
WEEKLY_WINDOW_DAYS = 7

_broadcast_running = [False]
_broadcast_task = [None]


def is_running() -> bool:
    return _broadcast_running[0]


def stop_broadcast():
    _broadcast_running[0] = False


def get_status() -> dict:
    sent_total = storage.tg_broadcast_sent_count()
    sent_week = storage.tg_broadcast_sent_in_last_days(WEEKLY_WINDOW_DAYS)
    return {
        "sent_total": sent_total,
        "sent_this_week": sent_week,
        "weekly_limit": WEEKLY_LIMIT,
        "remaining_this_week": max(0, WEEKLY_LIMIT - sent_week),
    }


async def run_broadcast(client, report_chat_id: int, admin_id: int, limit: int = None):
    """
    1. Берём последнее сообщение из Saved Messages (пост для рассылки)
    2. Шлём по номерам из clients, кому ещё не отправляли (tg_sent=0)
    3. Не превышаем недельный лимит (скользящее окно 7 дней)
    4. limit (если передан) — доп. потолок именно на этот запуск, для тестовых пачек
    """
    # Смотрим последние несколько сообщений и пропускаем команды (/broadcast и т.п.) —
    # если команда была написана прямо в Избранное, она сама становится последним
    # сообщением, а нам нужен реальный пост под ней.
    recent = await client.get_messages("me", limit=10)
    post = next(
        (m for m in recent if m and not (m.raw_text or "").strip().startswith("/")),
        None
    )
    if not post:
        await client.send_message(admin_id, "❌ Избранное пустое (или там только команды) — сохрани туда пост с фото и текстом, потом повтори /broadcast")
        return

    sent_this_week = storage.tg_broadcast_sent_in_last_days(WEEKLY_WINDOW_DAYS)
    remaining_week = max(0, WEEKLY_LIMIT - sent_this_week)
    if remaining_week == 0:
        await client.send_message(
            admin_id,
            f"⚠️ Недельный лимит уже исчерпан: {sent_this_week}/{WEEKLY_LIMIT} за последние {WEEKLY_WINDOW_DAYS} дней.\n"
            f"Попробуй позже — лимит скользящий, освобождается постепенно."
        )
        return

    run_cap = min(limit, remaining_week) if limit else remaining_week
    batch = storage.get_unsent_tg_clients(run_cap)
    total_batch = len(batch)

    if total_batch == 0:
        await client.send_message(admin_id, "✅ Отправлять больше некому — все номера уже получили рассылку.")
        return

    await logger.tg(
        f"📢 Начинаю рассылку в Telegram\nВ этом запуске: {total_batch}\n"
        f"Использовано за неделю: {sent_this_week}/{WEEKLY_LIMIT}",
        "info"
    )
    await client.send_message(admin_id,
        f"📢 Запускаю рассылку\nСообщение: {'фото + текст' if post.photo else 'текст'}\n"
        f"В этом запуске: {total_batch} | За неделю: {sent_this_week}/{WEEKLY_LIMIT}\n\n"
        f"Остановить: /stopbroadcast"
    )

    sent = 0
    failed = 0
    _broadcast_running[0] = True

    for i, phone in enumerate(batch, 1):
        if not _broadcast_running[0]:
            await logger.tg(f"🛑 Рассылка остановлена вручную. Отправлено в этом запуске: {sent}", "warn")
            await client.send_message(admin_id, f"🛑 Рассылка остановлена. Отправлено: {sent}/{total_batch}")
            return

        try:
            entity = await client.get_input_entity(f"+{phone}")
            await client.forward_messages(entity, post)
            storage.mark_tg_client_sent(phone)  # коммитится сразу — устойчивость к рестарту
            sent += 1
        except Exception as e:
            failed += 1
            err_short = str(e)[:80]
            print(f"[BROADCAST] Не удалось отправить {phone}: {err_short}")

        if i % 25 == 0:
            await logger.tg(f"📨 Рассылка: {sent} отправлено, {failed} ошибок, осталось {total_batch - i}", "info")

        if i % PAUSE_CHUNK == 0:
            await asyncio.sleep(PAUSE_BETWEEN + PAUSE_CHUNK_EXTRA)
        else:
            await asyncio.sleep(PAUSE_BETWEEN)

    _broadcast_running[0] = False
    new_week_total = storage.tg_broadcast_sent_in_last_days(WEEKLY_WINDOW_DAYS)
    await logger.tg(
        f"✅ Рассылка завершена\nОтправлено: {sent}/{total_batch} | Ошибок: {failed}\n"
        f"Использовано за неделю: {new_week_total}/{WEEKLY_LIMIT}",
        "info"
    )
    await client.send_message(admin_id,
        f"✅ Рассылка завершена!\nОтправлено: {sent}/{total_batch}\nОшибок: {failed}\n"
        f"За неделю: {new_week_total}/{WEEKLY_LIMIT}"
    )
