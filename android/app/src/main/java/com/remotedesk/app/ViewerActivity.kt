package com.remotedesk.app

import android.graphics.Bitmap
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import kotlin.math.abs

/**
 * نمایشگر: اتصال به میزبان (رایانه یا گوشی)، دیدن صفحه و کنترل با لمس.
 *
 * حرکات:
 * - لمس و کشیدن با یک انگشت → ماوس چپ (کلیک = لمس کوتاه)
 * - لمس طولانی → کلیک راست
 * - کشیدن عمودی با دو انگشت → اسکرول
 * - پنل کیبورد: تایپ متن + کلیدهای ویژه + نگه‌داشتن Ctrl/Alt/Shift
 */
class ViewerActivity : AppCompatActivity(), ViewerClient.Listener {

    private val ui = Handler(Looper.getMainLooper())

    private lateinit var connectPanel: View
    private lateinit var viewerPanel: View
    private lateinit var screenView: ScreenView
    private lateinit var etHost: EditText
    private lateinit var etPort: EditText
    private lateinit var etName: EditText
    private lateinit var etPin: EditText
    private lateinit var etKeys: EditText
    private lateinit var tvConnectStatus: TextView
    private lateinit var tvViewerStatus: TextView
    private lateinit var btnConnect: Button
    private lateinit var keyboardPanel: View
    private lateinit var btnCtrl: Button
    private lateinit var btnAlt: Button
    private lateinit var btnShift: Button

    private var client: ViewerClient? = null

    // وضعیت لمس
    private var downTime = 0L
    private var downX = 0f
    private var downY = 0f
    private var lastTwoY = Float.MIN_VALUE
    private val heldMods = LinkedHashSet<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_viewer)

        connectPanel = findViewById(R.id.connectPanel)
        viewerPanel = findViewById(R.id.viewerPanel)
        screenView = findViewById(R.id.screenView)
        etHost = findViewById(R.id.etHost)
        etPort = findViewById(R.id.etPort)
        etName = findViewById(R.id.etName)
        etPin = findViewById(R.id.etPin)
        etKeys = findViewById(R.id.etKeys)
        tvConnectStatus = findViewById(R.id.tvConnectStatus)
        tvViewerStatus = findViewById(R.id.tvViewerStatus)
        btnConnect = findViewById(R.id.btnConnect)
        keyboardPanel = findViewById(R.id.keyboardPanel)
        btnCtrl = findViewById(R.id.btnCtrl)
        btnAlt = findViewById(R.id.btnAlt)
        btnShift = findViewById(R.id.btnShift)

        findViewById<Button>(R.id.btnDisconnect).setOnClickListener { disconnect() }
        findViewById<Button>(R.id.btnKeyboard).setOnClickListener { toggleKeyboard() }

        // کلیدهای ویژه (فشردن + رها کردن)
        bindSpecial(R.id.btnEnter, "ENTER")
        bindSpecial(R.id.btnBackspace, "BACKSPACE")
        bindSpecial(R.id.btnEsc, "ESC")
        bindSpecial(R.id.btnTab, "TAB")
        bindSpecial(R.id.btnHome, "HOME")
        bindSpecial(R.id.btnEnd, "END")
        bindSpecial(R.id.btnPgUp, "PAGE_UP")
        bindSpecial(R.id.btnPgDn, "PAGE_DOWN")
        bindSpecial(R.id.btnLeft, "LEFT")
        bindSpecial(R.id.btnUp, "UP")
        bindSpecial(R.id.btnDown, "DOWN")
        bindSpecial(R.id.btnRight, "RIGHT")

        // کلیدهای اصلاح‌گر (نگه‌داشتن)
        bindModifier(btnCtrl, "CTRL")
        bindModifier(btnAlt, "ALT")
        bindModifier(btnShift, "SHIFT")

        // تایپ متن → ارسال کاراکتر به مقصد
        etKeys.addTextChangedListener(object : android.text.TextWatcher {
            private var lastLen = 0
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: android.text.Editable?) {
                val text = s?.toString() ?: return
                val additions = text.length - lastLen
                lastLen = if (additions > 0) text.length else 0
                if (additions > 0) {
                    val ch = text.lastOrNull() ?: return
                    val mods = synchronized(heldMods) { heldMods.toList() }
                    client?.key(ch.toString(), true, mods.ifEmpty { null })
                    client?.key(ch.toString(), false)
                    // خالی کردن برای تایپ بعدی
                    if (text.length > 40) {
                        etKeys.setText("")
                    }
                }
            }
        })

        setupTouch()

        btnConnect.setOnClickListener { connect() }
    }

    // ---------------- اتصال ----------------

    private fun connect() {
        val host = etHost.text.toString().trim()
        if (host.isEmpty()) {
            Toast.makeText(this, R.string.toast_host_required, Toast.LENGTH_SHORT).show()
            return
        }
        val port = etPort.text.toString().trim().toIntOrNull() ?: Proto.PORT
        val name = etName.text.toString().trim().ifEmpty { "گوشی" }
        val pin = etPin.text.toString().trim()

        btnConnect.isEnabled = false
        tvConnectStatus.text = getString(R.string.connecting)
        client = ViewerClient(host, port, name, pin, this).also { it.start() }
    }

    private fun disconnect() {
        client?.shutdown()
        client = null
    }

    // ---------------- رویدادهای کلاینت (نخ شبکه) ----------------

    override fun onAuthOk(w: Int, h: Int) {
        ui.post {
            connectPanel.visibility = View.GONE
            viewerPanel.visibility = View.VISIBLE
            keyboardPanel.visibility = View.GONE
            tvViewerStatus.text = "متصل — صفحه مقصد: ${w}×${h}"
            client?.quality(0.55, 55)  // تنظیم کیفیت متناسب با موبایل
        }
    }

    override fun onAuthFail(msg: String) {
        ui.post {
            Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
            tvConnectStatus.text = getString(R.string.viewer_status)
            btnConnect.isEnabled = true
            backToConnect()
        }
    }

    override fun onStatus(text: String) {
        ui.post { tvViewerStatus.text = text }
    }

    override fun onFrame(bitmap: Bitmap) {
        // نمایشگر تصویر باید روی نخ UI آپدیت شود
        ui.post { screenView.setFrame(bitmap) }
    }

    override fun onClosed() {
        ui.post {
            backToConnect()
            btnConnect.isEnabled = true
            tvConnectStatus.text = getString(R.string.viewer_status)
            client = null
        }
    }

    private fun backToConnect() {
        viewerPanel.visibility = View.GONE
        connectPanel.visibility = View.VISIBLE
    }

    // ---------------- لمس ----------------

    private fun setupTouch() {
        screenView.setOnTouchListener { v, ev ->
            val c = client
            if (c == null || !c.authed) return@setOnTouchListener false
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downTime = SystemClock.elapsedRealtime()
                    downX = ev.x
                    downY = ev.y
                    lastTwoY = Float.MIN_VALUE
                    screenView.normalized(ev.x, ev.y)?.let { (x, y) ->
                        c.mouse(x, y, "down", "left")
                    }
                }
                MotionEvent.ACTION_POINTER_DOWN -> {
                    lastTwoY = Float.MIN_VALUE
                }
                MotionEvent.ACTION_MOVE -> {
                    if (ev.pointerCount >= 2) {
                        // اسکرول با دو انگشت
                        val y = (ev.getY(0) + ev.getY(1)) / 2f
                        if (lastTwoY != Float.MIN_VALUE) {
                            val dy = ((lastTwoY - y) / 60f).toInt()
                            if (dy != 0) {
                                val p = screenView.normalized(ev.getX(0), ev.getY(0))
                                if (p != null) c.mouse(p.first, p.second, "wheel", dy = dy)
                            }
                        }
                        lastTwoY = y
                    } else {
                        val p = screenView.normalized(ev.x, ev.y)
                        if (p != null) c.mouse(p.first, p.second, "move")
                    }
                }
                MotionEvent.ACTION_UP -> {
                    val held = SystemClock.elapsedRealtime() - downTime
                    val moved = abs(ev.x - downX) + abs(ev.y - downY)
                    val p = screenView.normalized(ev.x, ev.y)
                    if (p != null) {
                        if (held > 550 && moved < 30) {
                            // لمس طولانی = کلیک راست (چپ را رها و راست کلیک کن)
                            c.mouse(p.first, p.second, "up", "left")
                            c.mouse(p.first, p.second, "down", "right")
                            c.mouse(p.first, p.second, "up", "right")
                        } else {
                            c.mouse(p.first, p.second, "up", "left")
                        }
                    }
                    lastTwoY = Float.MIN_VALUE
                }
            }
            v.performClick()
            true
        }
    }

    // ---------------- کیبورد ----------------

    private fun bindSpecial(viewId: Int, keyName: String) {
        findViewById<Button>(viewId).setOnClickListener {
            client?.key(keyName, true)
            client?.key(keyName, false)
        }
    }

    private fun bindModifier(btn: Button, mod: String) {
        btn.setOnClickListener {
            val nowHeld: Boolean
            synchronized(heldMods) {
                nowHeld = if (heldMods.contains(mod)) {
                    heldMods.remove(mod)
                    false
                } else {
                    heldMods.add(mod)
                    true
                }
            }
            client?.key(mod, nowHeld)
            btn.alpha = if (nowHeld) 0.55f else 1f
        }
    }

    private fun toggleKeyboard() {
        val show = keyboardPanel.visibility != View.VISIBLE
        keyboardPanel.visibility = if (show) View.VISIBLE else View.GONE
        if (show) etKeys.requestFocus()
    }

    // ---------------- چرخه عمر ----------------

    override fun onDestroy() {
        super.onDestroy()
        client?.shutdown()
        client = null
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (viewerPanel.visibility == View.VISIBLE) {
            disconnect()
        } else {
            AlertDialog.Builder(this)
                .setTitle("خروج")
                .setMessage("از صفحه اتصال خارج می‌شوید؟")
                .setPositiveButton(R.string.accept) { _, _ -> super.onBackPressed() }
                .setNegativeButton(R.string.deny, null)
                .show()
        }
    }
}
