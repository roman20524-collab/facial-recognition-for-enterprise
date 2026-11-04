"""Почта и Telegram не влияют на решение о доступе."""
import io
import os
import smtplib
import threading
import time
from email.message import EmailMessage
import requests
import qrcode


def qr_png(token):
    output = io.BytesIO()
    qrcode.make(token).save(output, format='PNG')
    return output.getvalue()


def send_qr(email, name, token, expires):
    host = os.getenv('SMTP_HOST')
    sender = os.getenv('SMTP_FROM')
    if not host or not sender:
        raise RuntimeError('Настройте SMTP_HOST и SMTP_FROM в .env')
    message = EmailMessage()
    message['From'], message['To'] = sender, email
    message['Subject'] = 'Ваш пропуск'
    message.set_content(f'{name}, ваш QR-пропуск действует до {expires}.\n'
                        'Не передавайте изображение другим людям.')
    message.add_attachment(qr_png(token), maintype='image', subtype='png', filename='pass.png')
    port = int(os.getenv('SMTP_PORT', '465'))
    use_ssl = os.getenv('SMTP_SSL', '1') == '1'
    client = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with client(host, port, timeout=15) as smtp:
        if not use_ssl:
            smtp.starttls()
        if os.getenv('SMTP_USER'):
            smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        smtp.send_message(message)


_notify_lock = threading.Lock()
_last_sent = {}

def notify(raw, result):
    token, chat = os.getenv('TELEGRAM_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat:
        return
    key = (result['name'], result['allowed'])
    with _notify_lock:
        if time.monotonic() - _last_sent.get(key, -60) < 60:
            return
        _last_sent[key] = time.monotonic()
    caption = f"{result['name']}: {result['status']}\n{result['time']}"
    response = requests.post(f'https://api.telegram.org/bot{token}/sendPhoto',
                             data={'chat_id': chat, 'caption': caption},
                             files={'photo': ('camera.jpg', raw, 'image/jpeg')}, timeout=10)
    response.raise_for_status()
