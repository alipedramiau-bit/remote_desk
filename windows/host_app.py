# -*- coding: utf-8 -*-
"""رابط گرافیکی میزبان (Host) — ویندوز.

این رایانه صفحه خود را به اشتراک می‌گذارد:
- نمایش PIN اتصال و امکان بازتولید
- انتخاب حالت احراز هویت: رمز عبور / تائید دستی / هر دو
- پنجره تائید یا رد درخواست اتصال
- فهرست نمایشگرهای متصل و گزارش رویدادها
"""

import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import host_server
from capture import MssFrameSource
from protocol import DEFAULT_PORT


def local_ips():
    """پیدا کردن IPهای محلی دستگاه."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    ips.discard('127.0.0.1')
    return sorted(ips) or ['127.0.0.1']


class HostApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ریموت دسک — میزبان')
        self.geometry('560x600')
        self.minsize(520, 560)

        self.server = None
        self._capture_thread = None
        self._running = False
        self._approval_queue = queue.Queue()

        self._build_ui()
        self.after(200, self._poll)

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {'padx': 10, 'pady': 6}

        top = ttk.LabelFrame(self, text='آدرس این رایانه')
        top.pack(fill='x', **pad)
        self.ip_var = tk.StringVar(value=', '.join(local_ips()))
        ttk.Label(top, text='آدرس‌های IP (به این آدرس‌ها وصل می‌شوند):').pack(anchor='e', **pad)
        ttk.Label(top, textvariable=self.ip_var, font=('Tahoma', 10, 'bold'),
                  foreground='#0b5394').pack(anchor='e', **pad)

        auth = ttk.LabelFrame(self, text='احراز هویت')
        auth.pack(fill='x', **pad)
        row = ttk.Frame(auth); row.pack(fill='x', **pad)
        ttk.Label(row, text='رمز اتصال (PIN):').pack(side='right', padx=6)
        self.pin_var = tk.StringVar(value=host_server.generate_pin())
        self.pin_entry = ttk.Entry(row, textvariable=self.pin_var, width=12,
                                   justify='center', font=('Tahoma', 11, 'bold'))
        self.pin_entry.pack(side='right', padx=6)
        ttk.Button(row, text='بازتولید', command=self._regen_pin).pack(side='right', padx=6)

        row2 = ttk.Frame(auth); row2.pack(fill='x', **pad)
        ttk.Label(row2, text='حالت اتصال:').pack(side='right', padx=6)
        self.mode_var = tk.StringVar(value='both')
        ttk.Radiobutton(row2, text='رمز عبور', variable=self.mode_var,
                        value='password').pack(side='right', padx=8)
        ttk.Radiobutton(row2, text='تائید دستی', variable=self.mode_var,
                        value='approval').pack(side='right', padx=8)
        ttk.Radiobutton(row2, text='هر دو', variable=self.mode_var,
                        value='both').pack(side='right', padx=8)

        opts = ttk.LabelFrame(self, text='تنظیمات تصویر')
        opts.pack(fill='x', **pad)
        row3 = ttk.Frame(opts); row3.pack(fill='x', **pad)
        ttk.Label(row3, text='پورت:').pack(side='right', padx=6)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(row3, textvariable=self.port_var, width=8, justify='center').pack(side='right')
        ttk.Label(row3, text='کیفیت JPEG:').pack(side='right', padx=(18, 6))
        self.quality_var = tk.StringVar(value='60')
        ttk.Spinbox(row3, from_=30, to=90, textvariable=self.quality_var, width=6,
                    justify='center').pack(side='right')
        ttk.Label(row3, text='مقیاس صفحه:').pack(side='right', padx=(18, 6))
        self.scale_var = tk.StringVar(value='0.6')
        ttk.Spinbox(row3, from_=0.3, to=1.0, increment=0.1, textvariable=self.scale_var,
                    width=6, justify='center').pack(side='right')

        self.start_btn = ttk.Button(self, text='شروع اشتراک‌گذاری', command=self.start_host)
        self.start_btn.pack(fill='x', **pad)
        self.stop_btn = ttk.Button(self, text='توقف', command=self.stop_host, state='disabled')
        self.stop_btn.pack(fill='x', **pad)

        cl = ttk.LabelFrame(self, text='نمایشگرهای متصل')
        cl.pack(fill='both', expand=True, **pad)
        self.client_list = tk.Listbox(cl, height=5, font=('Tahoma', 10))
        self.client_list.pack(fill='both', expand=True, padx=8, pady=6)

        lg = ttk.LabelFrame(self, text='گزارش رویدادها')
        lg.pack(fill='both', expand=True, **pad)
        self.log_text = tk.Text(lg, height=6, state='disabled', font=('Tahoma', 9))
        self.log_text.pack(fill='both', expand=True, padx=8, pady=6)

        self.status_var = tk.StringVar(value='غیرفعال — برای شروع دکمه بالا را بزنید')
        ttk.Label(self, textvariable=self.status_var, foreground='#666').pack(anchor='e', **pad)

    def _regen_pin(self):
        self.pin_var.set(host_server.generate_pin())

    # ---------------- کنترل سرور ----------------
    def start_host(self):
        if self._running:
            return
        try:
            port = int(self.port_var.get())
            quality = int(self.quality_var.get())
            scale = float(self.scale_var.get())
        except ValueError:
            messagebox.showerror('خطا', 'پورت، کیفیت و مقیاس باید عدد باشند.')
            return
        pin = self.pin_var.get().strip()
        mode = self.mode_var.get()
        pin_required = mode in ('password', 'both') and bool(pin)
        approval_required = mode in ('approval', 'both')
        if mode in ('password', 'both') and not pin:
            messagebox.showerror('خطا', 'برای حالت رمز عبور، PIN را وارد کنید.')
            return

        src = MssFrameSource(scale=scale, quality=quality)
        self.server = host_server.HostServer(
            pin=pin, pin_required=pin_required, approval_required=approval_required,
            frame_source=src, approve_callback=self._ask_approve,
            log_callback=lambda t: self._log(t))
        try:
            self.server.start()
        except Exception as e:
            messagebox.showerror('خطا', 'راه‌اندازی سرور ناموفق بود:\n%s' % e)
            self.server = None
            return

        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        self.start_btn['state'] = 'disabled'
        self.stop_btn['state'] = 'normal'
        self.status_var.set('فعال — در انتظار اتصال نمایشگرها (پورت %d)' % port)

    def stop_host(self):
        self._running = False
        if self.server:
            self.server.stop()
            self.server = None
        self.start_btn['state'] = 'normal'
        self.stop_btn['state'] = 'disabled'
        self.client_list.delete(0, 'end')
        self.status_var.set('غیرفعال')

    # ---------------- نخ گرفتن تصویر ----------------
    def _capture_loop(self):
        import time
        while self._running and self.server:
            try:
                if self.server.authed_count() > 0:
                    jpeg, w, h = self.server.frame_source.capture()
                    self.server.publish_frame(jpeg)
                    time.sleep(0.045)  # حداکثر ~22fps
                else:
                    time.sleep(0.3)
            except Exception as e:
                self._log('خطای گرفتن تصویر: %s' % e)
                time.sleep(1.0)

    # ---------------- تائید اتصال ----------------
    def _ask_approve(self, name, addr):
        """از نخ اتصال صدا زده می‌شود؛ تصمیم را از نخ GUI می‌گیرد (timeout 90s)."""
        ev = threading.Event()
        box = {'allow': False}
        self._approval_queue.put((name, addr, ev, box))
        if ev.wait(90):
            return box['allow']
        return False

    # ---------------- حلقه رابط ----------------
    def _poll(self):
        # درخواست‌های تائید
        try:
            while True:
                name, addr, ev, box = self._approval_queue.get_nowait()
                allow = messagebox.askyesno(
                    'درخواست اتصال',
                    'کاربر «%s» از آدرس %s می‌خواهد به این رایانه متصل شود.\n\n'
                    'اجازه اتصال می‌دهید؟' % (name, addr),
                    parent=self)
                box['allow'] = bool(allow)
                ev.set()
        except queue.Empty:
            pass

        # فهرست کلاینت‌ها
        if self.server:
            items = ['%s — %s %s' % (n, a, '✓' if ok else '...') for n, a, ok in
                     self.server.client_list()]
            current = self.client_list.get(0, 'end')
            if list(current) != items:
                self.client_list.delete(0, 'end')
                for it in items:
                    self.client_list.insert('end', it)
            self.status_var.set('فعال — %d نمایشگر متصل (پورت %d)' %
                                (self.server.authed_count(), self.server.port))
        self.after(400, self._poll)

    def _log(self, text):
        def append():
            self.log_text['state'] = 'normal'
            self.log_text.insert('end', '• %s\n' % text)
            self.log_text.see('end')
            self.log_text['state'] = 'disabled'
        try:
            self.after(0, append)
        except Exception:
            pass

    def on_close(self):
        self._running = False
        if self.server:
            self.server.stop()
        self.destroy()


def main():
    app = HostApp()
    app.protocol('WM_DELETE_WINDOW', app.on_close)
    app.mainloop()


if __name__ == '__main__':
    main()
