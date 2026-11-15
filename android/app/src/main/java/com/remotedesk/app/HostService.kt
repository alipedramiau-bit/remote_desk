package com.remotedesk.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.IntentCompat
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.IOException
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean

/**
 * سرویس پیش‌زمینه میزبانی: پذیرش اتصال رایانه‌ها و ارسال تصویر صفحه.
 * رویدادهای ماوس/کیبورد رایانه پذیرفته نمی‌شود (اندروید تزریق ورودی خارجی را اجازه نمی‌دهد).
 */
class HostService : Service() {

    companion object {
        const val EXTRA_RESULT_CODE = "resultCode"
        const val EXTRA_RESULT_DATA = "resultData"
        private const val CHANNEL_ID = "remote_desk_host"
        private const val NOTIF_ID = 1001
        private const val TAG = "HostService"
        private const val TARGET_FPS_MS = 90L      // ~11 فریم بر ثانیه
        private const val JPEG_QUALITY = 50

        fun localIp(): String? {
            try {
                val nis = NetworkInterface.getNetworkInterfaces() ?: return null
                for (ni in nis) {
                    for (addr in ni.inetAddresses) {
                        if (addr is Inet4Address && !addr.isLoopbackAddress &&
                            !addr.isLinkLocalAddress
                        ) {
                            return addr.hostAddress
                        }
                    }
                }
            } catch (_: Exception) {
            }
            return null
        }
    }

    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var imageThread: HandlerThread? = null
    private var serverSocket: ServerSocket? = null
    private val running = AtomicBoolean(false)
    private val bus = FrameBus()
    private val clients = CopyOnWriteArrayList<HostClient>()
    @Volatile private var lastSentAt = 0L

    inner class HostClient(val socket: Socket) {
        val out: DataOutputStream =
            DataOutputStream(BufferedOutputStream(socket.getOutputStream(), 256 * 1024))
        @Volatile var authed = false
        @Volatile var alive = true
        @Volatile var lastVersion = 0L
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!running.compareAndSet(false, true)) {
            Log.w(TAG, "سرویس از قبل در حال اجراست")
            return START_NOT_STICKY
        }
        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, -1) ?: -1
        val resultData = intent?.let {
            IntentCompat.getParcelableExtra(it, EXTRA_RESULT_DATA, Intent::class.java)
        }
        if (resultData == null || resultCode < 0) {
            Log.e(TAG, "داده‌های MediaProjection دریافت نشد")
            stopSelf()
            return START_NOT_STICKY
        }
        startForegroundCompat()
        HostState.running = true
        HostState.statusText = "اشتراک فعال"
        startProjection(resultCode, resultData)
        Thread({ acceptLoop() }, "AcceptLoop").start()
        return START_NOT_STICKY
    }

    // ---------- پیش‌زمینه و نوتیفیکیشن ----------

    private fun startForegroundCompat() {
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID, getString(R.string.notif_channel),
                    NotificationManager.IMPORTANCE_LOW
                )
            )
        }
        val notif = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_monitor)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_text))
            .setOngoing(true)
            .build()
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            ServiceCompat.startForeground(
                this, NOTIF_ID, notif,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            )
        } else {
            startForeground(NOTIF_ID, notif)
        }
    }

    // ---------- MediaProjection ----------

    private fun startProjection(resultCode: Int, data: Intent) {
        val mgr =
            getSystemService(Context.MEDIA_PROJECTION_SERVICE) as android.media.projection.MediaProjectionManager
        val mp = mgr.getMediaProjection(resultCode, data)
        projection = mp
        mp.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                Log.i(TAG, "MediaProjection متوقف شد")
                stopSelf()
            }
        }, Handler(Looper.getMainLooper()))

        val metrics = resources.displayMetrics
        var w = metrics.widthPixels
        var h = metrics.heightPixels
        // محدود به حداکثر 1280 پیکسل در ضلع بزرگ برای پهنای باند معقول
        val maxSide = 1280
        if (w > maxSide || h > maxSide) {
            val scale = maxSide.toFloat() / maxOf(w, h)
            w = (w * scale).toInt()
            h = (h * scale).toInt()
        }

        val thread = HandlerThread("ImageReaderThread")
        thread.start()
        imageThread = thread

        val reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        reader.setOnImageAvailableListener({ r -> onImageAvailable(r) },
            Handler(thread.looper))
        imageReader = reader

        virtualDisplay = mp.createVirtualDisplay(
            "RemoteDesk",
            w, h, metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface, null, Handler(thread.looper)
        )
        Log.i(TAG, "VirtualDisplay آماده شد: ${w}x${h}")
    }

    private fun onImageAvailable(reader: ImageReader) {
        var image: Image? = null
        try {
            // کنترل نرخ فریم
            val now = android.os.SystemClock.elapsedRealtime()
            image = reader.acquireLatestImage() ?: return
            if (now - lastSentAt < TARGET_FPS_MS) return
            lastSentAt = now

            val bitmap = imageToBitmap(image)
            if (bitmap != null) {
                val bos = ByteArrayOutputStream()
                bitmap.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, bos)
                bus.publish(bos.toByteArray())
                bitmap.recycle()
            }
        } catch (e: Exception) {
            Log.e(TAG, "خطای پردازش فریم", e)
        } finally {
            try {
                image?.close()
            } catch (_: Exception) {
            }
        }
    }

    /** تبدیل Image (RGBA_8888) به Bitmap با مدیریت rowStride ناهم‌راستا. */
    private fun imageToBitmap(image: Image): Bitmap? {
        return try {
            val plane = image.planes[0]
            val buffer = plane.buffer
            val width = image.width
            val height = image.height
            val rowStride = plane.rowStride
            val pixelStride = plane.pixelStride

            if (rowStride == width * pixelStride) {
                val bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                buffer.rewind()
                bmp.copyPixelsFromBuffer(buffer)
                bmp
            } else {
                val row = ByteArray(rowStride)
                val pixels = IntArray(width * height)
                for (y in 0 until height) {
                    buffer.position(y * rowStride)
                    buffer.get(row, 0, rowStride)
                    for (x in 0 until width) {
                        val off = x * pixelStride
                        val r = row[off].toInt() and 0xFF
                        val g = row[off + 1].toInt() and 0xFF
                        val b = row[off + 2].toInt() and 0xFF
                        val a = row[off + 3].toInt() and 0xFF
                        pixels[y * width + x] = (a shl 24) or (r shl 16) or (g shl 8) or b
                    }
                }
                Bitmap.createBitmap(pixels, width, height, Bitmap.Config.ARGB_8888)
            }
        } catch (e: Exception) {
            Log.e(TAG, "تبدیل تصویر ناموفق", e)
            null
        }
    }

    // ---------- شبکه ----------

    private fun acceptLoop() {
        try {
            val ss = ServerSocket()
            ss.reuseAddress = true
            ss.bind(InetSocketAddress(Proto.PORT))
            serverSocket = ss
            HostState.statusText = "در انتظار اتصال رایانه…"
            while (running.get()) {
                val sock = ss.accept()
                sock.tcpNoDelay = true
                val client = HostClient(sock)
                clients.add(client)
                Thread({ handleClient(client) }, "Client-${sock.inetAddress.hostAddress}").start()
            }
        } catch (e: Exception) {
            if (running.get()) Log.e(TAG, "حلقه پذیرش پایان یافت", e)
        } finally {
            cleanup()
        }
    }

    private fun handleClient(client: HostClient) {
        val addr = client.socket.inetAddress.hostAddress ?: "?"
        try {
            client.socket.soTimeout = 30_000
            val inp = DataInputStream(BufferedInputStream(client.socket.getInputStream()))

            val (type, body) = Proto.readMsg(inp)
            if (type != Proto.MSG_JSON) throw IOException("پیام اول JSON نیست")
            val hello = Proto.parse(body)
            if (hello.optString("t") != "auth") throw IOException("دستور احراز هویت نامعتبر")
            val name = hello.optString("name", "کاربر").take(32)

            // 1) بررسی PIN
            if (hello.optString("pin", "") != HostState.pin) {
                sendJsonSafe(client, Proto.msg("auth_fail", "msg" to "رمز عبور نادرست است"))
                HostState.statusText = "رمز نادرست از $addr"
                return
            }

            // 2) تائید دستی (اختیاری)
            var approved = true
            if (HostState.approvalRequired) {
                sendJsonSafe(client, Proto.msg("wait_approval"))
                approved = HostState.requestApproval(name, addr)
            }
            if (!approved) {
                sendJsonSafe(
                    client,
                    Proto.msg("auth_fail", "msg" to "کاربر مقصد اتصال را نپذیرفت")
                )
                HostState.statusText = "درخواست $name رد شد"
                return
            }

            client.authed = true
            val rd = imageReader
            sendJsonSafe(
                client,
                Proto.msg("auth_ok", "proto" to 1, "w" to (rd?.width ?: 0), "h" to (rd?.height ?: 0))
            )
            HostState.statusText = "متصل: $name ($addr)"
            Log.i(TAG, "کلاینت متصل شد: $name ($addr)")

            Thread({ frameSender(client) }, "Sender-$addr").start()

            // حلقه دستورات — کنترل ورودی گوشی از رایانه پذیرفته نیست
            var inputWarned = false
            while (client.alive && running.get()) {
                val (t2, b2) = Proto.readMsg(inp)
                if (t2 != Proto.MSG_JSON) continue
                when (Proto.parse(b2).optString("t")) {
                    "mouse", "key" -> {
                        if (!inputWarned) {
                            sendJsonSafe(
                                client, Proto.msg(
                                    "info",
                                    "msg" to "کنترل ورودی در حالت میزبانی گوشی پشتیبانی نمی‌شود"
                                )
                            )
                            inputWarned = true
                        }
                    }
                    "ping" -> sendJsonSafe(client, Proto.msg("pong"))
                    "disconnect" -> return
                }
            }
        } catch (e: Exception) {
            Log.d(TAG, "پایان کلاینت $addr: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            client.alive = false
            client.authed = false
            try {
                client.socket.close()
            } catch (_: Exception) {
            }
            clients.remove(client)
            if (running.get()) {
                HostState.statusText =
                    if (clients.any { it.authed }) HostState.statusText else "در انتظار اتصال رایانه…"
            }
        }
    }

    private fun frameSender(client: HostClient) {
        while (client.alive && client.authed && running.get()) {
            val item = bus.waitNew(client.lastVersion, 5000) ?: continue
            val (jpeg, ver) = item
            try {
                synchronized(client.out) {
                    Proto.sendFrame(client.out, jpeg)
                }
                client.lastVersion = ver
            } catch (e: Exception) {
                client.alive = false
                try {
                    client.socket.close()
                } catch (_: Exception) {
                }
            }
        }
    }

    private fun sendJsonSafe(client: HostClient, obj: JSONObject) {
        try {
            synchronized(client.out) {
                Proto.sendJson(client.out, obj)
            }
        } catch (_: Exception) {
        }
    }

    // ---------- پایان ----------

    override fun onDestroy() {
        running.set(false)
        HostState.running = false
        HostState.statusText = "غیرفعال"
        try {
            serverSocket?.close()
        } catch (_: Exception) {
        }
        for (c in clients) {
            c.alive = false
            try {
                c.socket.close()
            } catch (_: Exception) {
            }
        }
        clients.clear()
        try {
            virtualDisplay?.release()
        } catch (_: Exception) {
        }
        try {
            imageReader?.close()
        } catch (_: Exception) {
        }
        try {
            projection?.stop()
        } catch (_: Exception) {
        }
        imageThread?.quitSafely()
        imageThread = null
        super.onDestroy()
    }

    private fun cleanup() {
        stopSelf()
    }
}
