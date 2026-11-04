"""Проверка правил API без камеры, почты и Telegram: py -m unittest -v."""
import io
import hashlib
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import numpy as np
import config
import server

class FakeEngine:
    def extract(self, raw):
        if raw != b'face':
            raise ValueError('Некорректное фото')
        return np.array([1, 0], dtype=np.float32)

    def identify(self, raw, people):
        return (people[0], 0.9) if raw == b'face' and people else (None, 0.1)

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = patch.multiple(config, DB=Path(self.temp.name)/'test.db',
                                       ADMIN_KEY='admin-test', CAMERA_KEY='camera-test')
        self.settings.start()
        self.client = server.create_app(FakeEngine()).test_client()
        self.admin = {'X-API-Key':'admin-test'}
        self.camera = {'X-API-Key':'camera-test'}
        self.notification = patch('server.notify')
        self.notification.start()

    def tearDown(self):
        self.notification.stop()
        self.settings.stop()
        self.temp.cleanup()

    def add(self, qr=False):
        result = self.client.post('/api/people', headers=self.admin,
                                 data={'name':'Роман', 'email':'test@example.com',
                                       'require_qr':'1' if qr else '0',
                                       'photo':(io.BytesIO(b'face'),'face.jpg')})
        self.assertEqual(result.status_code, 201)
        return result.json['id']

    def check(self, raw=b'face', qr=''):
        return self.client.post('/api/check', headers=self.camera,
                                data={'photo':(io.BytesIO(raw),'frame.jpg'), 'qr':qr}).json

    def test_roles_and_unknown(self):
        self.assertEqual(self.client.get('/api/people').status_code, 401)
        self.assertEqual(self.client.get('/api/people', headers=self.camera).status_code, 401)
        result = self.check(b'unknown')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['name'], 'Unknown')

    def test_face_and_delete(self):
        person = self.add()
        self.assertTrue(self.check()['allowed'])
        self.assertEqual(self.client.delete('/api/people/'+person, headers=self.admin).status_code, 200)
        self.assertFalse(self.check()['allowed'])

    def test_required_qr_and_expiry(self):
        self.add(qr=True)
        self.assertFalse(self.check()['allowed'])
        with patch('server.send_qr') as mail:
            person = self.client.get('/api/people', headers=self.admin).json[0]['id']
            response = self.client.post('/api/people/'+person+'/qr', headers=self.admin)
            self.assertEqual(response.status_code, 200)
            token = mail.call_args.args[2]
            expiry = mail.call_args.args[3]
        self.assertEqual(server.datetime.fromisoformat(expiry).hour, 0)
        self.assertTrue(self.check(qr=token)['allowed'])
        self.assertFalse(self.check(raw=b'unknown', qr=token)['allowed'])
        with patch('server.now', return_value=server.datetime.fromisoformat(expiry)):
            self.assertFalse(self.check(qr=token)['allowed'])

    def test_mail_error_revokes_pass(self):
        person = self.add(qr=True)
        with patch('server.send_qr', side_effect=RuntimeError('SMTP unavailable')):
            response = self.client.post('/api/people/'+person+'/qr', headers=self.admin)
        self.assertEqual(response.status_code, 502)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM passes').fetchone()[0], 0)

    def test_unique_codes_and_wrong_owner(self):
        first = self.add(qr=True)
        second = self.add(qr=True)
        tokens=[]
        with patch('server.send_qr') as mail:
            for person in [first, first, second]:
                self.client.post('/api/people/'+person+'/qr', headers=self.admin)
                tokens.append(mail.call_args.args[2])
        self.assertEqual(len(set(tokens)), 3)
        self.assertFalse(self.check(qr=tokens[-1])['allowed'])
        self.client.delete('/api/people/'+first, headers=self.admin)
        self.assertFalse(self.check(qr=tokens[0])['allowed'])

if __name__ == '__main__':
    unittest.main()
