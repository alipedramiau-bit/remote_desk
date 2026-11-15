package com.remotedesk.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.nio.charset.StandardCharsets

/**
 * نخ کلاینت نمایشگر: اتصال، احراز هویت، دریافت فریم‌ها، ارسال ورودی.
 */
class ViewerClient(
    private val host: String,
    private val port: Int,
    private val name: String,
    private val pin: String,
    private val listener: Listener
) : Thread() {

    interface Listener {
        fun onAuthOk(w: Int, h: Int)          // در نخ شبکه صدا زده می‌شود
        fun onAuthFail(msg: String)           // در نخ شبکه
        fun onStatus(text: String)            // در نخ شبکه
        fun onFrame(bitmap: Bitmap)           // در نخ شبکه
        fun onClosed()                        // در نخ شبکه
    }

    @Volatile private var alive = true
    @Volatile var authed = false
        private set
    private var socket: Socket? = null
    private var out: DataOutputStream? = null
    private val sendLock = Object()

    override fun run() {
        try {
            val s = Socket()
            s.connect(InetSocketAddress(host, port), 15000)
            s.tcpNoDelay = true
            socket = s
            val o = DataOutputStream(BufferedOutputStream(s.getOutputStream(), 256 * 1024))
            out = o
            val inp = DataInputStream(BufferedInputStream(s.getInputStream()))

            Proto.sendJson(o, Proto.msg("auth", "name" to name, "pin" to pin, "proto" to 1))

            // احراز هویت
            var w = 0
            var h = 0
            while (alive && !authed) {
                val (type, body) = Proto.readMsg(inp)
                if (type != Proto.MSG_JSON) continue
                val m = Proto.parse(body)
                when (m.optString("t")) {
                    "wait_approval" -> listener.onStatus("در انتظار تائید کاربر مقصد…")
                    "auth_ok" -> {
                        authed = true
                        w = m.optInt("w", 0)
                        h = m.optInt("h", 0)
                        listener.onAuthOk(w, h)
                    }
                    "auth_fail" -> {
                        listener.onAuthFail(m.optString("msg", "احراز هویت ناموفق بود"))
                        return
                    }
                }
            }
            if (!authed) return

            s.soTimeout = 500
            startPingLoop()

            // حلقه دریافت
            while (alive && authed) {
                val (type, body) = try {
                    Proto.readMsg(inp)
                } catch (e: SocketTimeoutException) {
                    continue
                }
                when (type) {
                    Proto.MSG_FRAME -> {
                        val bmp = BitmapFactory.decodeByteArray(body, 0, body.size)
                        if (bmp != null) listener.onFrame(bmp)
                    }
                    Proto.MSG_JSON -> {
                        val m = Proto.parse(body)
                        if (m.optString("t") == "info") {
                            listener.onStatus(m.optString("msg"))
                        }
                    }
                }
            }
        } catch (e: Exception) {
            if (alive && !authed) listener.onAuthFail("اتصال ناموفق: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            alive = false
            listener.onClosed()
        }
    }

    private fun startPingLoop() {
        val pinger = Thread {
            while (alive && authed) {
                try {
                    Thread.sleep(25_000)
                } catch (e: InterruptedException) {
                    return@Thread
                }
                sendJson(Proto.msg("ping"))
            }
        }
        pinger.isDaemon = true
        pinger.start()
    }

    // ---------- ارسال ----------

    fun sendJson(obj: JSONObject) {
        if (!authed || !alive) return
        val o = out ?: return
        synchronized(sendLock) {
            try {
                Proto.sendJson(o, obj)
            } catch (e: Exception) {
                alive = false
            }
        }
    }

    fun mouse(x: Float, y: Float, action: String, btn: String = "left", dy: Int = 0) {
        sendJson(
            Proto.msg(
                "mouse",
                "x" to x.toDouble(), "y" to y.toDouble(),
                "action" to action, "btn" to btn, "dy" to dy
            )
        )
    }

    fun key(keyName: String, pressed: Boolean = true, mods: List<String>? = null) {
        val kv = mutableListOf<Pair<String, Any?>>(
            "key" to keyName, "pressed" to pressed
        )
        if (!mods.isNullOrEmpty()) kv.add("mods" to mods)
        sendJson(Proto.msg("key", *kv.toTypedArray()))
    }

    fun quality(scale: Double, q: Int) {
        sendJson(Proto.msg("quality", "scale" to scale, "q" to q))
    }

    fun shutdown() {
        alive = false
        try {
            sendJson(Proto.msg("disconnect"))
        } catch (_: Exception) {
        }
        try {
            socket?.close()
        } catch (_: Exception) {
        }
    }
}
