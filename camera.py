"""Камера посылает кадр и QR серверу; решение принимает только API."""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
import config


def draw_label(frame, text, allowed):
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    fonts = ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    font = next((ImageFont.truetype(p, 22) for p in fonts if Path(p).exists()), ImageFont.load_default())
    draw.rectangle((0, 0, image.width, 100), fill=(15, 20, 30))
    draw.text((12, 10), text, font=font, fill=(95, 235, 140) if allowed else (255, 145, 145))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def check(frame, qr):
    success, encoded = cv2.imencode('.jpg', frame)
    if not success:
        raise ValueError('Не удалось создать JPEG')
    response = requests.post(config.API_URL + '/api/check', headers={'X-API-Key': config.CAMERA_KEY},
                             files={'photo': ('frame.jpg', encoded.tobytes(), 'image/jpeg')},
                             data={'qr': qr}, timeout=12)
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='0', help='Номер камеры, путь к видео или фотографии')
    args = parser.parse_args()
    if not config.CAMERA_KEY:
        raise SystemExit('Заполните CAMERA_KEY в .env')
    if Path(args.input).suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.bmp'):
        frame = cv2.imdecode(np.fromfile(args.input, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise SystemExit('Изображение не прочитано')
        qr, _, _ = cv2.QRCodeDetector().detectAndDecode(frame)
        print(check(frame, qr))
        return
    source = int(args.input) if args.input.isdigit() else args.input
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit('Камера не открылась. Попробуйте --input 1')
    scanner = cv2.QRCodeDetector()
    pool = ThreadPoolExecutor(max_workers=1)
    pending, next_check = None, 0
    qr_cache, qr_deadline = '', 0
    label, allowed = 'Ожидание проверки...', False
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            qr, _, _ = scanner.detectAndDecode(frame)
            if qr:
                qr_cache, qr_deadline = qr, time.monotonic() + 5
            if time.monotonic() > qr_deadline:
                qr_cache = ''
            if pending and pending.done():
                try:
                    result = pending.result()
                    allowed = result['allowed']
                    label = f"{result['name']} — {result['status']}\n{result['reason']}"
                    print(result)
                except (requests.RequestException, ValueError, KeyError):
                    allowed, label = False, 'Нет ответа API — вход запрещён'
                pending = None
            if pending is None and time.monotonic() >= next_check:
                pending = pool.submit(check, frame.copy(), qr_cache)
                next_check = time.monotonic() + 3
                # Старое разрешение не действует во время следующей проверки.
                allowed, label = False, 'Проверка...'
            cv2.imshow('Camera | Q - exit', draw_label(frame, label, allowed))
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
