# -*- coding: utf-8 -*-
"""پروتکل ارتباطی ریموت دسک (مشترک بین میزبان و نمایشگر).

قالب هر پیام روی سوکت TCP:
    4 بایت طول بدنه (Big-Endian, unsigned int)
    1 بایت  نوع پیام (1=JSON کنترلی، 2=فریم JPEG)
    n بایت  بدنه

پیام‌های کنترلی JSON همیشه دارای کلید "t" هستند (نوع دستور).
مختصات ماوس به‌صورت نرمال‌شده 0..1 ارسال می‌شود تا تغییر رزولوشن مقصد، کنترل را نشکند.
"""

import json
import struct

PROTO_VERSION = 1
DEFAULT_PORT = 48500

MSG_JSON = 1    # پیام کنترلی/دستوری (JSON)
MSG_FRAME = 2   # فریم تصویر (JPEG خام)

MAX_MSG_SIZE = 25 * 1024 * 1024  # سقف ایمنی برای اندازه پیام (۲۵ مگابایت)


def send_msg(sock, mtype, body):
    """ارسال یک پیام قالب‌بندی‌شده؛ body بایت خام است."""
    header = struct.pack('>IB', len(body), mtype)
    sock.sendall(header + body)


def recv_exact(sock, n):
    """دقیقاً n بایت می‌خواند؛ در صورت بسته‌شدن اتصال خطا می‌دهد."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(65536, n - len(buf)))
        if not chunk:
            raise ConnectionError('اتصال از طرف مقابل بسته شد')
        buf += chunk
    return bytes(buf)


def recv_msg(sock):
    """خواندن یک پیام کامل؛ خروجی: (نوع پیام، بایت‌های بدنه)."""
    header = recv_exact(sock, 5)
    length, mtype = struct.unpack('>IB', header)
    if length > MAX_MSG_SIZE:
        raise ValueError('پیام بیش از حد بزرگ است: %d' % length)
    return mtype, recv_exact(sock, length)


# ---------- helpers سطح بالا ----------

def send_json(sock, obj):
    """ارسال یک آبجکت dict به‌صورت پیام JSON."""
    send_msg(sock, MSG_JSON, json.dumps(obj, ensure_ascii=False).encode('utf-8'))


def recv_json_msg(sock):
    """خواندن پیام بعدی اگر JSON باشد؛ خروجی: dict."""
    mtype, body = recv_msg(sock)
    if mtype != MSG_JSON:
        raise ValueError('به‌جای JSON، پیام نوع %d رسید' % mtype)
    return json.loads(body.decode('utf-8'))


def send_frame(sock, jpeg_bytes):
    """ارسال فریم JPEG."""
    send_msg(sock, MSG_FRAME, jpeg_bytes)


def msg(t, **kw):
    """ساخت سریع دیکشنری پیام با کلید الزامی t."""
    m = {'t': t}
    m.update(kw)
    return m


def build_mouse(x_norm, y_norm, action='move', btn='left', dy=0):
    """پیام ماوس؛ x/y نرمال‌شده بین 0 و 1. action: move|down|up|wheel"""
    return msg('mouse', x=round(float(x_norm), 6), y=round(float(y_norm), 6),
               action=action, btn=btn, dy=int(dy))


def build_key(key, pressed=True, mods=None):
    """پیام کلید؛ key یا نام کلید ویژه (مثل ENTER) یا کاراکتر یونیکد است."""
    m = msg('key', key=str(key), pressed=bool(pressed))
    if mods:
        m['mods'] = list(mods)
    return m
