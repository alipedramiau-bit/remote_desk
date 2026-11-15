# -*- coding: utf-8 -*-
"""لانچر ریموت دسک ویندوز — انتخاب نقش میزبان یا نمایشگر.

اجرا:
    python main.py          → پنجره انتخاب نقش
    python main.py host     → مستقیم میزبان
    python main.py viewer   → مستقیم نمایشگر
"""

import sys
import tkinter as tk
from tkinter import ttk


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ریموت دسک')
        self.geometry('420x300')
        self.resizable(False, False)

        ttk.Label(self, text='ریموت دسک', font=('Tahoma', 16, 'bold'),
                  foreground='#0b5394').pack(pady=(24, 4))
        ttk.Label(self, text='اشتراک صفحه و کنترل از راه دور در شبکه محلی',
                  foreground='#666').pack(pady=(0, 18))

        ttk.Button(self, text='میزبان می‌شوم (این رایانه اشتراک می‌شود)',
                   command=self.open_host).pack(fill='x', padx=40, pady=8, ipady=6)
        ttk.Button(self, text='نمایشگر می‌شوم (اتصال به رایانه دیگر)',
                   command=self.open_viewer).pack(fill='x', padx=40, pady=8, ipady=6)
        ttk.Label(self, text='ویندوز ۸ به بالا — Python 3.8+',
                  foreground='#999', font=('Tahoma', 8)).pack(pady=(14, 0))

    def open_host(self):
        self.destroy()
        import host_app
        host_app.main()

    def open_viewer(self):
        self.destroy()
        import viewer_app
        viewer_app.main()


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else '').lower()
    if arg == 'host':
        import host_app
        host_app.main()
    elif arg == 'viewer':
        import viewer_app
        viewer_app.main()
    else:
        app = Launcher()
        app.mainloop()


if __name__ == '__main__':
    main()
