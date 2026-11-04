"""API: реестр людей, решения о доступе, QR и журнал. Запуск: py server.py."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException
import config
from recognition import FaceEngine
from services import send_qr, notify


def connect():
    connection = sqlite3.connect(config.DB, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    return connection


def now():
    return datetime.now(config.TZ)


def create_app(engine=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
    engine = engine or FaceEngine()
    executor = ThreadPoolExecutor(max_workers=2)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS people (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
            require_qr INTEGER NOT NULL, feature BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS passes (
            hash TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
            expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, person_id TEXT, name TEXT NOT NULL,
            allowed INTEGER NOT NULL, time TEXT NOT NULL, reason TEXT NOT NULL);
        ''')

    def auth(role):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                expected = config.ADMIN_KEY if role == 'admin' else config.CAMERA_KEY
                supplied = request.headers.get('X-API-Key', '')
                if not expected or not hmac.compare_digest(supplied, expected):
                    return jsonify(error='Нет доступа'), 401
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    @app.get('/api/people')
    @auth('admin')
    def people():
        with connect() as db:
            rows = db.execute('SELECT id,name,email,require_qr FROM people ORDER BY name').fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post('/api/people')
    @auth('admin')
    def add_person():
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        if not name or len(name) > 150:
            raise ValueError('Введите имя длиной до 150 символов')
        if email and ('@' not in email or '\n' in email or '\r' in email):
            raise ValueError('Проверьте адрес почты')
        photo = request.files.get('photo')
        if photo is None:
            raise ValueError('Добавьте фотографию')
        feature = engine.extract(photo.read())
        person_id = secrets.token_hex(16)
        with connect() as db:
            db.execute('INSERT INTO people VALUES (?,?,?,?,?)',
                       (person_id, name, email, int(request.form.get('require_qr') == '1'), feature.tobytes()))
        return jsonify(id=person_id, name=name), 201

    @app.delete('/api/people/<person_id>')
    @auth('admin')
    def delete_person(person_id):
        with connect() as db:
            result = db.execute('DELETE FROM people WHERE id=?', (person_id,))
        return (jsonify(deleted=True), 200) if result.rowcount else (jsonify(error='Человек не найден'), 404)

    @app.post('/api/people/<person_id>/qr')
    @auth('admin')
    def issue_qr(person_id):
        with connect() as db:
            person = db.execute('SELECT * FROM people WHERE id=?', (person_id,)).fetchone()
        if person is None:
            return jsonify(error='Человек не найден'), 404
        if not person['email']:
            raise ValueError('Для выдачи QR укажите почту при добавлении человека')
        token = secrets.token_urlsafe(32)
        expires = (now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect() as db:
            db.execute('INSERT INTO passes VALUES (?,?,?)', (digest, person_id, expires.isoformat()))
        try:
            send_qr(person['email'], person['name'], token, expires.isoformat())
        except Exception:
            with connect() as db:
                db.execute('DELETE FROM passes WHERE hash=?', (digest,))
            return jsonify(error='Письмо не отправлено. Проверьте настройки SMTP. Пропуск отозван.'), 502
        return jsonify(sent=True, expires=expires.isoformat())

    @app.get('/api/events')
    @auth('admin')
    def events():
        with connect() as db:
            rows = db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 200').fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post('/api/check')
    @auth('camera')
    def check():
        photo = request.files.get('photo')
        raw = photo.read() if photo else b''
        token = request.form.get('qr', '')
        person, score, reason = None, 0.0, 'Лицо не распознано'
        with connect() as db:
            registered = db.execute('SELECT * FROM people').fetchall()
            if raw:
                try:
                    person, score = engine.identify(raw, registered)
                except ValueError as exc:
                    reason = str(exc)
            qr_person = None
            if token:
                digest = hashlib.sha256(token.encode()).hexdigest()
                qr_person = db.execute('''SELECT people.* FROM passes JOIN people
                    ON passes.person_id=people.id WHERE passes.hash=? AND passes.expires>?''',
                    (digest, now().isoformat())).fetchone()
            # QR дополняет лицо, но не подменяет его: украденного QR недостаточно.
            allowed = person is not None
            if person is not None:
                reason = 'Лицо распознано'
                if person['require_qr'] and (qr_person is None or qr_person['id'] != person['id']):
                    allowed, reason = False, 'Нужны лицо и действующий QR этого человека'
                elif token and (qr_person is None or qr_person['id'] != person['id']):
                    allowed, reason = False, 'QR недействителен или принадлежит другому человеку'
            instant = now()
            result = dict(name=person['name'] if person else 'Unknown', allowed=allowed,
                          status='Вход разрешён' if allowed else 'Вход запрещён',
                          time=instant.isoformat(), date=instant.date().isoformat(),
                          reason=reason, score=round(score, 4))
            db.execute('INSERT INTO events(person_id,name,allowed,time,reason) VALUES(?,?,?,?,?)',
                       (person['id'] if person else None, result['name'], int(allowed), result['time'], reason))
        if raw:
            def deliver():
                try:
                    notify(raw, result)
                except Exception:
                    app.logger.warning('Не удалось отправить фотографию в Telegram')
            executor.submit(deliver)
        return jsonify(result)

    return app


if __name__ == '__main__':
    if not config.ADMIN_KEY or not config.CAMERA_KEY or config.ADMIN_KEY == config.CAMERA_KEY:
        raise SystemExit('Заполните .env: ADMIN_KEY и CAMERA_KEY должны быть разными')
    create_app().run(host='127.0.0.1', port=5000, threaded=True, debug=False)
