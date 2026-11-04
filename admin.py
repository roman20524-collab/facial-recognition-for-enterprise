"""Отдельное настольное приложение администратора (Tkinter)."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor
import requests
import config


class Admin(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Управление пропусками')
        self.geometry('1000x700')
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.photo = ''
        self.name, self.email = tk.StringVar(), tk.StringVar()
        self.require_qr = tk.BooleanVar()
        self.status = tk.StringVar(value='Добавьте человека или выберите запись в таблице')
        form = ttk.Frame(self, padding=15)
        form.pack(fill='x')
        for label, variable in [('Имя', self.name), ('Почта для QR', self.email)]:
            ttk.Label(form, text=label).pack(anchor='w')
            ttk.Entry(form, textvariable=variable, width=60).pack(anchor='w', pady=4)
        ttk.Checkbutton(form, text='Для входа обязательно лицо + QR', variable=self.require_qr).pack(anchor='w')
        self.photo_label = ttk.Label(form, text='Фото не выбрано')
        self.photo_label.pack(anchor='w')
        buttons = ttk.Frame(form)
        buttons.pack(anchor='w', pady=10)
        self.actions = []
        for text, command in [('Выбрать фото', self.choose_photo), ('Добавить', self.add),
                              ('Обновить', self.refresh), ('Удалить выбранного', self.delete),
                              ('Отправить QR на почту', self.issue)]:
            button = ttk.Button(buttons, text=text, command=command)
            button.pack(side='left', padx=3)
            self.actions.append(button)
        ttk.Label(self, textvariable=self.status, padding=10).pack(fill='x')
        tabs = ttk.Notebook(self)
        tabs.pack(expand=True, fill='both', padx=15, pady=10)
        self.people = ttk.Treeview(tabs, columns=('name', 'email', 'qr'), show='headings')
        for key, label in [('name','Имя'), ('email','Почта'), ('qr','Обязательный QR')]:
            self.people.heading(key, text=label)
        tabs.add(self.people, text='Люди')
        self.events = ttk.Treeview(tabs, columns=('time','name','status','reason'), show='headings')
        for key, label in [('time','Время'), ('name','Имя'), ('status','Результат'), ('reason','Причина')]:
            self.events.heading(key, text=label)
        tabs.add(self.events, text='Последние 200 проверок')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    def request(self, method, path, **kwargs):
        response = requests.request(method, config.API_URL + path,
                                    headers={'X-API-Key': config.ADMIN_KEY}, timeout=35, **kwargs)
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f'Некорректный ответ API: HTTP {response.status_code}')
        if not response.ok:
            raise ValueError(data.get('error', f'HTTP {response.status_code}'))
        return data

    def run(self, job, done):
        for button in self.actions:
            button.state(['disabled'])
        self.status.set('Выполняется запрос...')
        future = self.pool.submit(job)
        def poll():
            if not future.done():
                self.after(100, poll)
                return
            for button in self.actions:
                button.state(['!disabled'])
            try:
                value = future.result()
            except Exception as error:
                self.status.set('Ошибка запроса')
                messagebox.showerror('Ошибка', str(error))
                return
            self.status.set('Готово')
            done(value)
        self.after(100, poll)

    def choose_photo(self):
        self.photo = filedialog.askopenfilename(filetypes=[('Фотографии','*.jpg *.jpeg *.png *.webp *.bmp')])
        self.photo_label.config(text=self.photo or 'Фото не выбрано')

    def add(self):
        if not self.photo or not self.name.get().strip():
            messagebox.showerror('Данные', 'Заполните имя и выберите фото с одним лицом')
            return
        path = self.photo
        data = dict(name=self.name.get().strip(), email=self.email.get().strip(),
                    require_qr='1' if self.require_qr.get() else '0')
        def job():
            with open(path, 'rb') as photo:
                return self.request('POST', '/api/people', data=data, files={'photo': photo})
        self.run(job, lambda _: self.refresh())

    def selected(self):
        selection = self.people.selection()
        if not selection:
            messagebox.showinfo('Выбор', 'Выберите человека на вкладке «Люди»')
            return None
        return selection[0]

    def delete(self):
        person_id = self.selected()
        if person_id and messagebox.askyesno('Удаление', 'Удалить человека и все его QR-пропуска?'):
            self.run(lambda: self.request('DELETE', '/api/people/' + person_id), lambda _: self.refresh())

    def issue(self):
        person_id = self.selected()
        if person_id:
            self.run(lambda: self.request('POST', '/api/people/' + person_id + '/qr'),
                     lambda data: messagebox.showinfo('QR отправлен', 'Действует до: ' + data['expires']))

    def refresh(self):
        def job():
            return self.request('GET', '/api/people'), self.request('GET', '/api/events')
        def display(data):
            for tree in (self.people, self.events):
                for item in tree.get_children():
                    tree.delete(item)
            for person in data[0]:
                self.people.insert('', 'end', iid=person['id'], values=(person['name'], person['email'],
                                   'Да' if person['require_qr'] else 'Нет'))
            for event in data[1]:
                self.events.insert('', 'end', values=(event['time'], event['name'],
                                   'Разрешён' if event['allowed'] else 'Запрещён', event['reason']))
        self.run(job, display)


if __name__ == '__main__':
    if not config.ADMIN_KEY:
        raise SystemExit('Заполните ADMIN_KEY в .env')
    Admin().mainloop()
