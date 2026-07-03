import os
import socket
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL = os.environ.get("GMAIL", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
LAWYER_EMAIL = os.environ.get("LAWYER_EMAIL", "")
FROM_NAME = os.environ.get("MAIL_FROM_NAME", "Business Law Consulting")

# Некоторые хостинги (Railway и др.) не имеют исходящего IPv6-маршрута,
# а DNS для smtp.gmail.com отдаёт и AAAA (IPv6), и A (IPv4) записи.
# smtplib/socket могут выбрать IPv6 первым — тогда получаем
# "[Errno 101] Network is unreachable". Принудительно резолвим только IPv4.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only_getaddrinfo


def send_html_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Отправка одного HTML-письма (для массовой рассылки). Возвращает True/False,
    без исключения наружу — вызывающий код сам решает, помечать адрес отправленным или нет."""
    if not (GMAIL and APP_PASSWORD):
        print("[MAIL] Пропущена отправка — не заданы GMAIL/APP_PASSWORD")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{FROM_NAME} <{GMAIL}>"
        msg["To"] = to_email
        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL, APP_PASSWORD)
            s.sendmail(GMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[MAIL ERROR] {to_email}: {e}")
        return False


def send_lead_email(client_name: str, phone: str, message_text: str, username: str) -> bool:
    if not (GMAIL and APP_PASSWORD and LAWYER_EMAIL):
        print("[MAIL] Пропущена отправка — не заданы GMAIL/APP_PASSWORD/LAWYER_EMAIL")
        return False
    try:
        body = (
            f"Новая заявка от клиента с анкетой\n\n"
            f"Имя: {client_name or '—'}\n"
            f"Телефон: {phone or '—'}\n"
            f"Telegram: @{username or '—'}\n\n"
            f"Сообщение:\n{message_text}"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"Новая заявка — {client_name or phone or username}"
        msg["From"] = f"BLC Bot <{GMAIL}>"
        msg["To"] = LAWYER_EMAIL

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL, APP_PASSWORD)
            s.sendmail(GMAIL, LAWYER_EMAIL, msg.as_string())
        return True
    except Exception as e:
        print(f"[MAIL ERROR] {e}")
        return False
