# -*- coding: utf-8 -*-
"""منبع فریم تصویر میزبان: گرفتن اسکرین‌شات با mss و تبدیل به JPEG با Pillow.

mss فقط روی ویندوز (یا هر سیستم با نمایشگر) نصب می‌شود؛ در محیط تست بدون نمایشگر
از FakeFrameSource استفاده می‌شود.
"""

import threading


class MssFrameSource(object):
    """گرفتن صفحه نمایش و تولید JPEG مقیاس‌شده."""

    def __init__(self, scale=0.6, quality=60, monitor=1):
        self.scale = float(scale)
        self.quality = int(quality)
        self.monitor = monitor  # 1 = صفحه اصلی در mss
        self._lock = threading.Lock()

    # --- اندازه بومی صفحه ---
    def get_size(self):
        try:
            import mss
            import ctypes
            if hasattr(ctypes, 'windll'):
                w = ctypes.windll.user32.GetSystemMetrics(0)
                h = ctypes.windll.user32.GetSystemMetrics(1)
                if w and h:
                    return int(w), int(h)
            with mss.mss() as sct:
                mon = sct.monitors[self.monitor]
                return int(mon['width']), int(mon['height'])
        except Exception:
            return 1920, 1080

    def set_quality(self, scale=None, quality=None):
        with self._lock:
            if scale:
                self.scale = max(0.2, min(1.0, float(scale)))
            if quality:
                self.quality = max(20, min(90, int(quality)))

    def capture(self):
        """یک فریم می‌گیرد؛ خروجی: (jpeg_bytes, w, h)."""
        with self._lock:
            scale, quality = self.scale, self.quality
        import mss
        from PIL import Image
        import io

        with mss.mss() as sct:
            mon = sct.monitors[self.monitor]
            raw = sct.grab(mon)
        img = Image.frombytes('RGB', raw.size, raw.bgra, 'raw', 'BGRX')
        if scale < 0.999:
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=quality)
        return buf.getvalue(), img.width, img.height


class FakeFrameSource(object):
    """منبع فریم ساختگی برای تست بدون نمایشگر (انیمیشن ساده متحرک)."""

    def __init__(self, width=800, height=500, scale=0.6, quality=60):
        self.width = int(width)
        self.height = int(height)
        self.scale = float(scale)
        self.quality = int(quality)
        self._tick = 0

    def get_size(self):
        return self.width, self.height

    def set_quality(self, scale=None, quality=None):
        if scale:
            self.scale = max(0.2, min(1.0, float(scale)))
        if quality:
            self.quality = max(20, min(90, int(quality)))

    def capture(self):
        from PIL import Image, ImageDraw
        import io
        self._tick += 1
        img = Image.new('RGB', (self.width, self.height), (18, 32, 62))
        d = ImageDraw.Draw(img)
        x = (self._tick * 7) % (self.width - 60)
        d.ellipse((x, 120, x + 60, 180), fill=(240, 180, 40))
        d.text((20, 20), 'FakeFrame tick=%d' % self._tick, fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=self.quality)
        return buf.getvalue(), self.width, self.height
