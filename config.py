"""Настройки всех трёх приложений из одного .env."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
DB = DATA / 'access.sqlite3'
TZ = ZoneInfo(os.getenv('TIMEZONE', 'USA/New_York'))
API_URL = os.getenv('API_URL', 'http://127.0.0.1:5000').rstrip('/')
ADMIN_KEY = os.getenv('ADMIN_KEY', '')
CAMERA_KEY = os.getenv('CAMERA_KEY', '')
