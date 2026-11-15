# -*- coding: utf-8 -*-
"""رابط گرافیکی نمایشگر (Viewer) — ویندوز.

به رایانه/گوشی مقصد وصل می‌شود، صفحه را می‌بیند و با ماوس/کیبورد کنترل می‌کند.
"""

import io
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from protocol import (DEFAULT_PORT, build_key, build_mouse, recv_msg,
                      send_json, MSG_JSON, MSG_FRAME)

QUALITY_PRESETS = {  # نام نمایشی → (scale, q)
    'کم (سریع)': (0.45, 45),
    'متوسط': (0.6, 60),
    'زیاد (کند)': (0.85, 78),
}

SPECIAL_KEYS = {
    'Return': 'ENTER', 'KP_Enter': 'ENTER', 'BackSpace': 'BACKSPACE',
    'Tab': 'TAB', 'Escape': 'ESC', 'Delete': 'DELETE', 'Insert': 'INSERT',
    'Home': 'HOME', 'End': 'END', 'Prior': 'PAGE_UP', 'Next': 'PAGE_DOWN',
    'Left': 'LEFT', 'Up': 'UP', 'Right': 'RIGHT', 'Down': 'DOWN',
    'space': 'SPACE', 'Caps_Lock': 'CAPSLOCK',
}
for _i in range(1, 13):
    SPECIAL_KEYS['F%d' % _i] = 'F%d' % _i

MOD_MASKS = {'CTRL': 0x0004, 'ALT': 0x20000, 'SHIFT': 0x0001}


class ViewerClient(threading.Thread):
    """نخ ارتباط با میزبان؛ فریم‌ها را رمزگشایی و به صف GUI می‌گذارد."""

    def __init__(self, host, port, name, pin, on_event):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.name = name
        self.pin = pin
        self.on_event = on_event  # callback(main-thread-safe از طریق صف)
        self.sock = None
        self.alive = True
        self.authed = False
        self.remote_size = (1920, 1080)
        self.send_lock = threading.Lock()

    def _emit(self, kind, **kw):
        kw['kind'] = kind
        self.on_event(kw)

    def run(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=15)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            send_json(self.sock, {'t': 'auth', 'name': self.name, 'pin': self.pin,
                                  'proto': 1})
            # پاسخ احراز هویت
            while True:
                mtype, body = recv_msg(self.sock)
                if mtype != MSG_JSON:
                    continue
                m = _json_loads(body)
                t = m.get('t')
                if t == 'wait_approval':
                    self._emit('status', text='در انتظار تائید کاربر مقصد…')
                    continue
                if t == 'auth_ok':
                    self.authed = True
                    self.remote_size = (int(m.get('w', 1920)), int(m.get('h', 1080)))
                    self._emit('auth_ok', w=self.remote_size[0], h=self.remote_size[1])
                    break
                if t == 'auth_fail':
                    self._emit('auth_fail', msg=m.get('msg', 'احراز هویت ناموفق بود'))
                    return
        except Exception as e:
            self._emit('auth_fail', msg='اتصال ناموفق: %s' % e)
            return

        self._ping_loop_start()
        try:
            self.sock.settimeout(0.5)
            while self.alive and self.authed:
                try:
                    mtype, body = recv_msg(self.sock)
                except socket.timeout:
                    continue
                if mtype == MSG_FRAME:
                    try:
                        img = Image.open(io.BytesIO(body))
                        img.load()
                    except Exception:
                        continue
                    self._emit('frame', image=img)
                elif mtype == MSG_JSON:
                    m = _json_loads(body)
                    if m.get('t') == 'info':
                        self._emit('status', text=m.get('msg', ''))
        except Exception:
            pass
        finally:
            self.alive = False
            self._emit('closed')

    def _ping_loop_start(self):
        def loop():
            while self.alive and self.authed:
                self.send_json_obj({'t': 'ping'})
                time.sleep(25)
        threading.Thread(target=loop, daemon=True).start()

    # ---------- ارسال ----------
    def _send_raw(self, obj):
        try:
            with self.send_lock:
                send_json(self.sock, obj)
        except Exception:
            self.alive = False

    def send_json_obj(self, obj):
        if self.authed and self.alive:
            threading.Thread(target=self._send_raw, args=(obj,), daemon=True).start()

    def send_mouse(self, x, y, action, btn='left', dy=0):
        self.send_json_obj(build_mouse(x, y, action, btn, dy))

    def send_key(self, key, pressed=True, mods=None):
        self.send_json_obj(build_key(key, pressed, mods))

    def send_quality(self, scale, q):
        self.send_json_obj({'t': 'quality', 'scale': scale, 'q': q})

    def close(self):
        self.alive = False
        try:
            self.send_json_obj({'t': 'disconnect'})
        except Exception:
            pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


def _json_loads(body):
    import json
    return json.loads(body.decode('utf-8'))


class ViewerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ریموت دسک — نمایشگر')
        self.geometry('1000x680')
        self.minsize(640, 480)

        self.client = None
        self._photo = None
        self._img_id = None
        self._view = None          # (ox, oy, scale, bw, bh)
        self._last_move_tx = 0.0
        self._events = queue.Queue()
        self._fps = 0
        self._fps_count = 0
        self._fps_time = time.time()
        self._fullscreen = False

        self._build_ui()
        self.after(33, self._poll)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.form = ttk.LabelFrame(self, text='اتصال به رایانه مقصد')
        self.form.pack(fill='x', padx=10, pady=8)
        r1 = ttk.Frame(self.form); r1.pack(fill='x', padx=8, pady=6)
        ttk.Label(r1, text='آدرس مقصد (IP):').pack(side='right', padx=6)
        self.host_var = tk.StringVar()
        ttk.Entry(r1, textvariable=self.host_var, width=22).pack(side='right')
        ttk.Label(r1, text='پورت:').pack(side='right', padx=(18, 6))
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(r1, textvariable=self.port_var, width=8, justify='center').pack(side='right')

        r2 = ttk.Frame(self.form); r2.pack(fill='x', padx=8, pady=6)
        ttk.Label(r2, text='نام شما:').pack(side='right', padx=6)
        self.name_var = tk.StringVar(value='کاربر')
        ttk.Entry(r2, textvariable=self.name_var, width=18).pack(side='right')
        ttk.Label(r2, text='رمز اتصال (PIN):').pack(side='right', padx=(18, 6))
        self.pin_var = tk.StringVar()
        ttk.Entry(r2, textvariable=self.pin_var, width=12, justify='center',
                  show='•').pack(side='right')
        ttk.Label(r2, text='کیفیت:').pack(side='right', padx=(18, 6))
        self.quality_var = tk.StringVar(value='متوسط')
        ttk.Combobox(r2, textvariable=self.quality_var, width=12, state='readonly',
                     values=list(QUALITY_PRESETS.keys())).pack(side='right')

        r3 = ttk.Frame(self.form); r3.pack(fill='x', padx=8, pady=6)
        self.connect_btn = ttk.Button(r3, text='اتصال', command=self.connect)
        self.connect_btn.pack(side='right', padx=6)
        self.status_form_var = tk.StringVar(value='وضعیت: قطع')
        ttk.Label(r3, textvariable=self.status_form_var).pack(side='right', padx=6)

        # نوار ابزار نمای صفحه
        self.toolbar = ttk.Frame(self)
        self.disc_btn = ttk.Button(self.toolbar, text='قطع اتصال', command=self.disconnect)
        self.disc_btn.pack(side='right', padx=6)
        self.fs_btn = ttk.Button(self.toolbar, text='تمام‌صفحه (F11)',
                                 command=self.toggle_fullscreen)
        self.fs_btn.pack(side='right', padx=6)
        self.status_var = tk.StringVar(value='')
        ttk.Label(self.toolbar, textvariable=self.status_var).pack(side='right', padx=12)
        # toolbar بعداً زیر canvas بسته می‌شود

        self.canvas = tk.Canvas(self, bg='#111', highlightthickness=0)
        self.canvas.bind('<Configure>', self._on_resize)

        # رویدادهای ماوس
        for seq, btn in (('<ButtonPress-1>', 'left'), ('<ButtonPress-3>', 'right'),
                         ('<ButtonPress-2>', 'middle')):
            self.canvas.bind(seq, lambda e, b=btn: self._mouse_btn(e, b, True))
        for seq, btn in (('<ButtonRelease-1>', 'left'), ('<ButtonRelease-3>', 'right'),
                         ('<ButtonRelease-2>', 'middle')):
            self.canvas.bind(seq, lambda e, b=btn: self._mouse_btn(e, b, False))
        self.canvas.bind('<B1-Motion>', self._mouse_move_drag)
        self.canvas.bind('<Motion>', self._mouse_move_hover)
        self.canvas.bind('<MouseWheel>', self._mouse_wheel)

        # رویدادهای کیبورد
        self.bind('<Key>', self._on_key)
        self.bind('<F11>', lambda e: self.toggle_fullscreen())

    # ---------------- اتصال ----------------
    def connect(self):
        host = self.host_var.get().strip()
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror('خطا', 'پورت باید عدد باشد.')
            return
        name = self.name_var.get().strip() or 'کاربر'
        pin = self.pin_var.get().strip()
        if not host:
            messagebox.showerror('خطا', 'آدرس مقصد را وارد کنید.')
            return
        if self.client:
            self.client.close()
        self.connect_btn['state'] = 'disabled'
        self.status_form_var.set('وضعیت: در حال اتصال…')
        preset = QUALITY_PRESETS.get(self.quality_var.get(), (0.6, 60))
        self.client = ViewerClient(host, port, name, pin, self._client_event)
        self._pending_quality = preset
        self.client.start()

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
        self._show_form()

    def _show_form(self):
        self.canvas.pack_forget()
        self.toolbar.pack_forget()
        self.form.pack(fill='x', padx=10, pady=8)
        self.connect_btn['state'] = 'normal'
        self.status_form_var.set('وضعیت: قطع')
        self.title('ریموت دسک — نمایشگر')

    def _show_view(self):
        self.form.pack_forget()
        self.toolbar.pack(side='bottom', fill='x', padx=10, pady=4)
        self.canvas.pack(fill='both', expand=True, padx=10, pady=(8, 4))
        self.canvas.focus_set()

    # ---------------- رویدادهای کلاینت (از صف) ----------------
    def _client_event(self, ev):
        self._events.put(ev)

    def _poll(self):
        try:
            while True:
                ev = self._events.get_nowait()
                k = ev['kind']
                if k == 'auth_ok':
                    self._show_view()
                    self.status_var.set('متصل — صفحه مقصد: %dx%d' % (ev['w'], ev['h']))
                    if self.client:
                        self.client.send_quality(*self._pending_quality)
                elif k == 'auth_fail':
                    messagebox.showerror('خطای اتصال', ev.get('msg', ''))
                    self.connect_btn['state'] = 'normal'
                    self.status_form_var.set('وضعیت: قطع')
                elif k == 'status':
                    self.status_var.set(ev.get('text', ''))
                elif k == 'frame':
                    self._display_frame(ev['image'])
                elif k == 'closed':
                    if self.client:
                        self.client = None
                    self._show_form()
        except queue.Empty:
            pass
        # شمارش fps
        self._fps_count += 1
        now = time.time()
        if now - self._fps_time >= 1.0:
            self._fps = self._fps_count
            self._fps_count = 0
            self._fps_time = now
            if self.client and self.client.authed:
                txt = 'متصل — %d فریم/ثانیه' % self._fps
                if self.client.remote_size:
                    txt += ' — صفحه مقصد: %dx%d' % self.client.remote_size
                self.status_var.set(txt)
        self.after(33, self._poll)

    # ---------------- نمایش فریم ----------------
    def _on_resize(self, _e):
        if self._photo:
            self._redraw()

    def _display_frame(self, img):
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        scale = min(cw / img.width, ch / img.height)
        disp_w = max(1, int(img.width * scale))
        disp_h = max(1, int(img.height * scale))
        disp = img.resize((disp_w, disp_h))
        self._photo = ImageTk.PhotoImage(disp)
        ox = (cw - disp_w) // 2
        oy = (ch - disp_h) // 2
        self._view = (ox, oy, scale, img.width, img.height)
        if self._img_id is None:
            self._img_id = self.canvas.create_image(ox, oy, image=self._photo, anchor='nw')
        else:
            self.canvas.coords(self._img_id, ox, oy)
            self.canvas.itemconfig(self._img_id, image=self._photo)
        self._redraw()

    def _redraw(self):
        if self._img_id is not None and self._photo:
            self.canvas.coords(self._img_id,
                               (self.canvas.winfo_width() - self._photo.width()) // 2,
                               (self.canvas.winfo_height() - self._photo.height()) // 2)

    def _norm_xy(self, e):
        """مختصات ماوس را به نرمال‌شده 0..1 صفحه مقصد تبدیل می‌کند."""
        if not self._view:
            return None
        ox, oy, scale, bw, bh = self._view
        x = (e.x - ox) / (scale * bw)
        y = (e.y - oy) / (scale * bh)
        if x < 0 or x > 1 or y < 0 or y > 1:
            x = max(0.0, min(1.0, x)); y = max(0.0, min(1.0, y))
        return x, y

    # ---------------- ماوس ----------------
    def _mouse_btn(self, e, btn, down):
        if not (self.client and self.client.authed):
            return
        p = self._norm_xy(e)
        if p:
            self.client.send_mouse(p[0], p[1], 'down' if down else 'up', btn)

    def _mouse_move_drag(self, e):
        if not (self.client and self.client.authed):
            return
        p = self._norm_xy(e)
        if p:
            self.client.send_mouse(p[0], p[1], 'move')

    def _mouse_move_hover(self, e):
        # حرکت بدون کلیک با محدودیت نرخ (هر 80ms) برای کاهش ترافیک
        if not (self.client and self.client.authed):
            return
        now = time.time()
        if now - self._last_move_tx < 0.08:
            return
        self._last_move_tx = now
        p = self._norm_xy(e)
        if p:
            self.client.send_mouse(p[0], p[1], 'move')

    def _mouse_wheel(self, e):
        if not (self.client and self.client.authed):
            return
        p = self._norm_xy(e)
        if p:
            clicks = 1 if e.delta > 0 else -1
            self.client.send_mouse(p[0], p[1], 'wheel', dy=clicks)

    # ---------------- کیبورد ----------------
    def _on_key(self, e):
        if not (self.client and self.client.authed):
            return
        if e.keysym == 'F11':
            return
        mods = [name for name, mask in MOD_MASKS.items() if e.state & mask]
        if e.keysym in SPECIAL_KEYS:
            self.client.send_key(SPECIAL_KEYS[e.keysym], True, mods or None)
            self.client.send_key(SPECIAL_KEYS[e.keysym], False)
        elif e.char:
            self.client.send_key(e.char, True, mods or None)
            self.client.send_key(e.char, False)

    # ---------------- سایر ----------------
    def toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.attributes('-fullscreen', self._fullscreen)

    def on_close(self):
        if self.client:
            self.client.close()
        self.destroy()


def main():
    app = ViewerApp()
    app.protocol('WM_DELETE_WINDOW', app.on_close)
    app.mainloop()


if __name__ == '__main__':
    main()
