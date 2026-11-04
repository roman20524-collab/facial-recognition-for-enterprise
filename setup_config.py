"""Первоначальная настройка без перезаписи существующего .env."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent
path = root / '.env'
if path.exists():
    print('.env уже существует; настройки сохранены')
else:
    text = (root / '.env.example').read_text(encoding='utf-8')
    text = text.replace('ADMIN_KEY=\n', 'ADMIN_KEY=' + secrets.token_urlsafe(32) + '\n')
    text = text.replace('CAMERA_KEY=\n', 'CAMERA_KEY=' + secrets.token_urlsafe(32) + '\n')
    path.write_text(text, encoding='utf-8')
    print('.env создан. Укажите SMTP и Telegram, если они нужны.')
