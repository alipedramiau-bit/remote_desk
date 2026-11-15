# -*- coding: utf-8 -*-
"""سرور میزبان ریموت دسک.

مسئولیت‌ها:
- پذیرش اتصال نمایشگرها روی TCP
- احراز هویت دو حالته: رمز عبور (PIN) و/یا تائید دستی کاربر مقصد
- ارسال فریم‌های JPEG به همه کلاینت‌های تاییدشده (FrameBus)
- دریافت و اعمال دستورات ماوس/کیبورد از نمایشگر
"""

import hmac
import json
import secrets
import socket
import threading

from protocol import (DEFAULT_PORT, MSG_JSON, PROTO_VERSION, recv_msg,
                      send_frame, send_json)


def generate_pin(n=6):
    """تولید رمز عددی امن."""
    return ''.join(secrets.choice('0123456789') for _ in range(n))


class FrameBus(object):
    """توزیع آخرین فریم به همه فرستنده‌ها؛ هر فریم فقط یک نسخه آخر نگه داشته می‌شود."""

    def __init__(self):
        self._cond = threading.Condition()
        self._jpeg = None
        self._version = 0

    def publish(self, jpeg):
        with self._cond:
            self._jpeg = jpeg
            self._version += 1
            self._cond.notify_all()

    def wait_new(self, last_version, timeout=5.0):
        """منتظر فریم تازه‌تر از last_version می‌ماند؛ خروجی (jpeg, version) یا None."""
        with self._cond:
            if self._version <= last_version:
                self._cond.wait(timeout)
            if self._version > last_version and self._jpeg is not None:
                return self._jpeg, self._version
            return None


class ClientConn(threading.Thread):
    """یک نمایشگر متصل؛ جریان: handshake → احراز هویت → ارسال فریم + حلقه دستورات."""

    def __init__(self, server, sock, addr):
        super().__init__(daemon=True)
        self.server = server
        self.sock = sock
        self.addr = addr
        self.name = 'ناشناس'
        self.authed = False
        self.alive = True
        self.last_frame_ver = 0
        self.send_lock = threading.Lock()

    # --- ارسال امن با قفل ---
    def try_send_json(self, obj):
        try:
            with self.send_lock:
                send_json(self.sock, obj)
            return True
        except Exception:
            return False

    def run(self):
        server = self.server
        try:
            self.sock.settimeout(120)
            ok, fail_msg = self._handshake()
            if not ok:
                self.try_send_json({'t': 'auth_fail', 'msg': fail_msg})
                return
            w, h = server.frame_source.get_size()
            if not self.try_send_json({'t': 'auth_ok', 'proto': PROTO_VERSION, 'w': w, 'h': h}):
                return
            self.authed = True
            server.add_client(self)
            server.log_event('اتصال برقرار شد: %s (%s:%s)' % (self.name, self.addr[0], self.addr[1]))
            sender = threading.Thread(target=self._frame_sender, daemon=True)
            sender.start()
            self._command_loop()
        except Exception as e:
            server.log_event('خطای اتصال %s: %s' % (self.addr[0], e))
        finally:
            self._cleanup()

    def _handshake(self):
        """دریافت پیام auth و اعمال سیاست‌های رمز/تائید. خروجی: (ok, پیام خطا)"""
        server = self.server
        mtype, body = recv_msg(self.sock)
        if mtype != MSG_JSON:
            return False, 'پیام اول باید JSON باشد'
        hello = json.loads(body.decode('utf-8'))
        if hello.get('t') != 'auth':
            return False, 'دستور احراز هویت نامعتبر است'
        self.name = str(hello.get('name') or 'ناشناس')[:32]
        pin = str(hello.get('pin') or '')

        # 1) بررسی رمز (اگر لازم باشد)
        if server.pin_required:
            if not hmac.compare_digest(pin, server.pin):
                server.log_event('رمز نادرست از %s' % self.addr[0])
                return False, 'رمز عبور نادرست است'

        # 2) تائید دستی کاربر مقصد (اگر لازم باشد)
        if server.approval_required:
            if not self.try_send_json({'t': 'wait_approval'}):
                return False, 'اتصال قطع شد'
            approved = server.ask_approval(self.name, '%s:%s' % (self.addr[0], self.addr[1]))
            if not approved:
                server.log_event('درخواست %s رد شد' % self.name)
                return False, 'کاربر مقصد اتصال را نپذیرفت'
        return True, ''

    def _frame_sender(self):
        while self.alive and self.authed:
            item = self.server.bus.wait_new(self.last_frame_ver, 5.0)
            if item is None:
                continue  # بدون فریم تازه؛ حلقه ادامه دارد
            jpeg, ver = item
            try:
                with self.send_lock:
                    send_frame(self.sock, jpeg)
                self.last_frame_ver = ver
            except Exception:
                self.alive = False
                break

    def _command_loop(self):
        self.sock.settimeout(300)
        while self.alive and self.authed:
            mtype, body = recv_msg(self.sock)
            if mtype != MSG_JSON:
                continue
            m = json.loads(body.decode('utf-8'))
            t = m.get('t')
            if t == 'mouse':
                self.server.input.handle_mouse(m)
            elif t == 'key':
                self.server.input.handle_key(m)
            elif t == 'quality':
                self.server.set_quality(m.get('scale'), m.get('q'))
            elif t == 'ping':
                self.try_send_json({'t': 'pong'})
            elif t == 'disconnect':
                break
            else:
                self.try_send_json({'t': 'info', 'msg': 'دستور ناشناخته رد شد'})

    def _cleanup(self):
        self.alive = False
        self.authed = False
        try:
            self.sock.close()
        except Exception:
            pass
        self.server.remove_client(self)


class HostServer(object):
    """سرور اصلی میزبان. استفاده:
        srv = HostServer(pin='123456', pin_required=True, approval_required=True,
                         frame_source=src, approve_callback=cb)
        srv.start()
        srv.publish_frame(jpeg)   # در نخ جداگانه از منبع فریم
        srv.stop()
    """

    def __init__(self, pin='', pin_required=True, approval_required=False,
                 frame_source=None, approve_callback=None, input_controller=None,
                 log_callback=None, host='', port=DEFAULT_PORT):
        self.pin = str(pin)
        self.pin_required = bool(pin_required)
        self.approval_required = bool(approval_required)
        self.frame_source = frame_source
        self.approve_callback = approve_callback
        self.input = input_controller
        self.log_callback = log_callback
        self.host = host
        self.port = int(port)
        self.bus = FrameBus()
        self._clients = []
        self._clients_lock = threading.Lock()
        self._lsock = None
        self._accept_thread = None
        self._running = False

        if self.input is None:
            from input_inject import get_input_controller
            self.input = get_input_controller()

    # ---------- چرخه عمر ----------
    def start(self):
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._lsock.bind((self.host, self.port))
        self._lsock.listen(5)
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        self.log_event('سرور روی پورت %d فعال شد' % self.port)

    def stop(self):
        self._running = False
        for c in self._clients:
            c.alive = False
            try:
                c.sock.close()
            except Exception:
                pass
        with self._clients_lock:
            self._clients = []
        if self._lsock:
            try:
                self._lsock.close()
            except Exception:
                pass
        self.log_event('سرور متوقف شد')

    def _accept_loop(self):
        while self._running:
            try:
                sock, addr = self._lsock.accept()
            except (OSError, ValueError):
                break
            if not self._running:
                break
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn = ClientConn(self, sock, addr)
            with self._clients_lock:
                self._clients.append(conn)
            conn.start()

    # ---------- مدیریت کلاینت‌ها ----------
    def add_client(self, conn):
        with self._clients_lock:
            self._clients.append(conn)

    def remove_client(self, conn):
        with self._clients_lock:
            if conn in self._clients:
                self._clients.remove(conn)
        if conn.authed:
            self.log_event('خروج کلاینت: %s' % conn.name)

    def authed_count(self):
        with self._clients_lock:
            return sum(1 for c in self._clients if c.authed)

    def client_list(self):
        with self._clients_lock:
            return [(c.name, '%s:%s' % (c.addr[0], c.addr[1]), c.authed) for c in self._clients]

    # ---------- فریم و تنظیمات ----------
    def publish_frame(self, jpeg):
        self.bus.publish(jpeg)

    def set_quality(self, scale=None, quality=None):
        if self.frame_source:
            self.frame_source.set_quality(scale, quality)

    def log_event(self, text):
        if self.log_callback:
            try:
                self.log_callback(text)
            except Exception:
                pass

    def ask_approval(self, name, addr):
        """پرسش تائید از کاربر مقصد؛ بدون callback، درخواست رد می‌شود (امن‌تر)."""
        if self.approve_callback is None:
            return False
        try:
            return bool(self.approve_callback(name, addr))
        except Exception:
            return False
