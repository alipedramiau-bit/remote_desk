# -*- coding: utf-8 -*-
"""تزریق ورودی (ماوس و کیبورد) در ویندوز با ctypes/SendInput — بدون وابستگی خارجی.

سازگار با ویندوز ۸ به بالا (Python 3.8+). روی سیستم‌های غیرویندوزی NullInput
جایگزین می‌شود تا کد هسته در محیط‌های تست هم اجرا شود.
"""

import ctypes
import sys

# ---------- پرچم‌های SendInput ----------

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# کد کلیدهای مجازی (Virtual-Key Codes ویندوز)
VK_MAP = {
    'ENTER': 0x0D, 'BACKSPACE': 0x08, 'TAB': 0x09, 'ESC': 0x1B, 'SPACE': 0x20,
    'DELETE': 0x2E, 'INSERT': 0x2D, 'HOME': 0x24, 'END': 0x23,
    'PAGE_UP': 0x21, 'PAGE_DOWN': 0x22,
    'LEFT': 0x25, 'UP': 0x26, 'RIGHT': 0x27, 'DOWN': 0x28,
    'CAPSLOCK': 0x14, 'SHIFT': 0xA0, 'CTRL': 0xA2, 'ALT': 0xA4, 'WIN': 0x5B,
}
for _i in range(1, 13):
    VK_MAP['F%d' % _i] = 0x6F + _i  # F1=0x70 ... F12=0x7B

MOD_KEYS = ('CTRL', 'ALT', 'SHIFT', 'WIN')

if sys.platform == 'win32':
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                    ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                    ('dwExtraInfo', ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
                    ('wParamH', wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ('u',)
        _fields_ = [('type', wintypes.DWORD), ('u', _INPUTUNION)]

    _user32 = ctypes.windll.user32
    _user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
    _user32.SendInput.restype = ctypes.c_uint
    _user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    _user32.GetSystemMetrics.restype = ctypes.c_int

    def _send(inp):
        return _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def screen_size():
        """اندازه صفحه اصلی (پیکسل)."""
        return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


class WindowsInput(object):
    """تزریق ماوس/کیبورد روی ویندوز با SendInput."""

    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('WindowsInput فقط روی ویندوز کار می‌کند')

    def _mouse(self, flags, dx=0, dy=0, wheel=0):
        mi = MOUSEINPUT(dx, dy, wheel & 0xFFFFFFFF, flags, 0, 0)
        inp = INPUT(INPUT_MOUSE)
        inp.mi = mi
        _send(inp)

    def move_abs(self, x, y):
        """انتقال مطلق ماوس به مختصات پیکسلی صفحه."""
        w, h = screen_size()
        nx = int(max(0.0, min(1.0, x)) * 65535)
        ny = int(max(0.0, min(1.0, y)) * 65535)
        self._mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny)

    def button(self, btn, down):
        """فشردن/رها کردن دکمه ماوس؛ btn: left|right|middle"""
        table = {
            ('left', True): MOUSEEVENTF_LEFTDOWN, ('left', False): MOUSEEVENTF_LEFTUP,
            ('right', True): MOUSEEVENTF_RIGHTDOWN, ('right', False): MOUSEEVENTF_RIGHTUP,
            ('middle', True): MOUSEEVENTF_MIDDLEDOWN, ('middle', False): MOUSEEVENTF_MIDDLEUP,
        }
        flag = table.get((btn, down))
        if flag:
            self._mouse(flag)

    def wheel(self, clicks):
        """اسکرول چرخ ماوس؛ مثبت = بالا."""
        self._mouse(MOUSEEVENTF_WHEEL, wheel=int(clicks * 120))

    def _key_vk(self, vk, down):
        inp = INPUT(INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(vk, 0, KEYEVENTF_SCANCODE if down == 2 else (0 if down else KEYEVENTF_KEYUP), 0, 0)
        # down==2 یعنی فقط scan-code بفرست (برای کلیدهای ویژه مطمئن‌تر است)
        if down == 0:
            inp.ki.dwFlags = KEYEVENTF_KEYUP | KEYEVENTF_SCANCODE
        _send(inp)

    def _key_unicode(self, ch, down):
        inp = INPUT(INPUT_KEYBOARD)
        flags = KEYEVENTF_UNICODE if down else (KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        inp.ki = KEYBDINPUT(0, ord(ch) & 0xFFFF, flags, 0, 0)
        _send(inp)

    def handle_mouse(self, m):
        """اعمال پیام ماوس دریافتی از نمایشگر؛ مختصات نرمال‌شده 0..1."""
        action = m.get('action', 'move')
        x = float(m.get('x', 0)); y = float(m.get('y', 0))
        if action == 'move':
            self.move_abs(x, y)
        elif action in ('down', 'up'):
            btn = m.get('btn', 'left')
            if btn not in ('left', 'right', 'middle'):
                btn = 'left'
            self.move_abs(x, y)
            self.button(btn, action == 'down')
        elif action == 'wheel':
            self.wheel(int(m.get('dy', 0)))

    def handle_key(self, k):
        """اعمال پیام کلید؛ key یا نام ویژه یا کاراکتر است. mods برای ترکیب Ctrl/Alt/Shift."""
        key = str(k.get('key', ''))
        pressed = bool(k.get('pressed', True))
        mods = k.get('mods') or []
        if key in VK_MAP:
            self._key_vk(VK_MAP[key], 2 if pressed else 0)
            return
        ch = key[0] if key else ''
        if not ch:
            return
        # کلیدهای ترکیبی: اول نگه‌داشتن کلیدهای اصلاح‌گر
        held = []
        try:
            for mod in mods:
                if mod in MOD_KEYS:
                    self._key_vk(VK_MAP[mod], 2)
                    held.append(mod)
            self._key_unicode(ch, pressed)
        finally:
            for mod in reversed(held):
                self._key_vk(VK_MAP[mod], 0)


class NullInput(object):
    """جایگزین غیرویندوزی: فقط رویداد را ثبت می‌کند (برای تست)."""

    def __init__(self):
        self.log = []

    def handle_mouse(self, m):
        self.log.append(('mouse', m))

    def handle_key(self, k):
        self.log.append(('key', k))


def get_input_controller():
    """انتخاب کنترل‌کننده ورودی متناسب با سیستم‌عامل."""
    if sys.platform == 'win32':
        return WindowsInput()
    return NullInput()
