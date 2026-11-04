"""YuNet находит лицо, SFace сравнивает признаки. Имена не участвуют в сравнении."""
import os
import threading
import cv2
import numpy as np
from config import ROOT

class FaceEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.detector = cv2.FaceDetectorYN.create(
            str(ROOT / 'models/face_detection_yunet_2023mar.onnx'), '', (320, 320), 0.85)
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(ROOT / 'models/face_recognition_sface_2021dec.onnx'), '')
        self.threshold = float(os.getenv('FACE_THRESHOLD', '0.50'))
        self.margin = float(os.getenv('FACE_MARGIN', '0.08'))

    def extract(self, raw):
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Файл не является изображением')
        h, w = image.shape[:2]
        if max(h, w) > 1600:
            image = cv2.resize(image, (int(w * 1600/max(h,w)), int(h * 1600/max(h,w))))
        with self.lock:
            self.detector.setInputSize((image.shape[1], image.shape[0]))
            _, faces = self.detector.detect(image)
            if faces is None or len(faces) != 1:
                raise ValueError('На фотографии должно быть ровно одно хорошо видимое лицо')
            aligned = self.recognizer.alignCrop(image, faces[0])
            feature = self.recognizer.feature(aligned).flatten().astype(np.float32)
        norm = np.linalg.norm(feature)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError('Не удалось получить признаки лица')
        return feature / norm

    def identify(self, raw, people):
        feature = self.extract(raw)
        scores = sorted(((float(feature @ np.frombuffer(p['feature'], np.float32)), p)
                         for p in people), key=lambda item: item[0], reverse=True)
        if not scores:
            return None, 0.0
        score, person = scores[0]
        ambiguous = len(scores) > 1 and score - scores[1][0] < self.margin
        if score < self.threshold or ambiguous:
            return None, score
        return person, score
