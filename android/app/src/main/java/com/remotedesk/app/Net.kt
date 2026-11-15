package com.remotedesk.app

import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.IOException
import java.nio.charset.StandardCharsets

/**
 * پروتکل ارتباطی ریموت دسک — مشترک با نسخه ویندوز (Python).
 * قالب پیام: [4 بایت طول BE][1 بایت نوع][بدنه] — نوع: 1=JSON، 2=JPEG
 */
object Proto {
    const val PORT = 48500
    const val MSG_JSON = 1
    const val MSG_FRAME = 2
    const val MAX_MSG = 25 * 1024 * 1024

    fun sendJson(out: DataOutputStream, obj: JSONObject) {
        synchronized(out) {
            val b = obj.toString().toByteArray(StandardCharsets.UTF_8)
            out.writeInt(b.size)
            out.writeByte(MSG_JSON)
            out.write(b)
            out.flush()
        }
    }

    fun sendFrame(out: DataOutputStream, jpeg: ByteArray) {
        synchronized(out) {
            out.writeInt(jpeg.size)
            out.writeByte(MSG_FRAME)
            out.write(jpeg)
            out.flush()
        }
    }

    fun readMsg(inp: DataInputStream): Pair<Int, ByteArray> {
        val len = inp.readInt()
        if (len < 0 || len > MAX_MSG) throw IOException("اندازه پیام نامعتبر: $len")
        val type = inp.readByte().toInt()
        val b = ByteArray(len)
        inp.readFully(b)
        return type to b
    }

    fun parse(body: ByteArray): JSONObject = JSONObject(String(body, StandardCharsets.UTF_8))

    fun msg(t: String, vararg kv: Pair<String, Any?>): JSONObject {
        val o = JSONObject()
        o.put("t", t)
        for ((k, v) in kv) if (v != null) o.put(k, v)
        return o
    }
}

/**
 * بافر توزیع آخرین فریم بین فرستنده‌های متصل.
 */
class FrameBus {
    private val lock = Object()
    private var jpeg: ByteArray? = null
    private var version = 0L

    fun publish(frame: ByteArray) {
        synchronized(lock) {
            jpeg = frame
            version++
            lock.notifyAll()
        }
    }

    fun waitNew(lastVersion: Long, timeoutMs: Long): Pair<ByteArray, Long>? {
        synchronized(lock) {
            if (version <= lastVersion) lock.wait(timeoutMs)
            val current = jpeg
            if (version > lastVersion && current != null) return current to version
            return null
        }
    }
}
