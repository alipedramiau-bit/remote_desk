package com.remotedesk.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.CheckBox
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ThreadLocalRandom

/**
 * میزبانی گوشی: اشتراک‌گذاری صفحه با MediaProjection.
 * رایانه با IP گوشی، پورت 48500 و PIN وصل می‌شود؛ هر اتصال (اختیاری) با تائید شما انجام می‌شود.
 *
 * توجه: در این حالت رایانه فقط صفحه را می‌بیند؛ کنترل لمسی گوشی از رایانه ممکن نیست.
 */
class HostActivity : AppCompatActivity() {

    private val ui = Handler(Looper.getMainLooper())

    private lateinit var tvPin: TextView
    private lateinit var tvStatus: TextView
    private lateinit var cbApproval: CheckBox
    private lateinit var btnStart: Button
    private lateinit var btnStop: Button
    private var sharing = false

    private val projectionManager by lazy {
        getSystemService(Context.MEDIA_PROJECTION_SERVICE) as android.media.projection.MediaProjectionManager
    }

    private val captureLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
            if (res.resultCode == RESULT_OK && res.data != null) {
                val svc = Intent(this, HostService::class.java)
                    .putExtra(HostService.EXTRA_RESULT_CODE, res.resultCode)
                    .putExtra(HostService.EXTRA_RESULT_DATA, res.data)
                ContextCompat.startForegroundService(this, svc)
                sharing = true
                updateUi()
            } else {
                Toast.makeText(this, R.string.projection_denied, Toast.LENGTH_SHORT).show()
            }
        }

    private val notifPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { _ ->
            launchCapture()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_host)

        tvPin = findViewById(R.id.tvPin)
        tvStatus = findViewById(R.id.tvHostStatus)
        cbApproval = findViewById(R.id.cbApproval)
        btnStart = findViewById(R.id.btnStartShare)
        btnStop = findViewById(R.id.btnStopShare)

        // PIN تصادفی ۶ رقمی
        val pin = if (Build.VERSION.SDK_INT >= 26) {
            String.format("%06d", ThreadLocalRandom.current().nextInt(1_000_000))
        } else {
            String.format("%06d", (Math.random() * 1_000_000).toInt())
        }
        HostState.pin = pin
        tvPin.text = pin

        btnStart.setOnClickListener {
            HostState.approvalRequired = cbApproval.isChecked
            if (Build.VERSION.SDK_INT >= 33 &&
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else {
                launchCapture()
            }
        }

        btnStop.setOnClickListener {
            stopService(Intent(this, HostService::class.java))
            sharing = false
            updateUi()
        }

        setApprovalListener()
    }

    private fun launchCapture() {
        captureLauncher.launch(projectionManager.createScreenCaptureIntent())
    }

    private fun setApprovalListener() {
        HostState.setApprovalListener { name, addr, future ->
            runOnUiThread { showApprovalDialog(name, addr, future) }
        }
    }

    private fun showApprovalDialog(
        name: String,
        addr: String,
        future: CompletableFuture<Boolean>
    ) {
        if (isFinishing || isDestroyed) {
            future.complete(false)
            return
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.approval_title)
            .setMessage(getString(R.string.approval_msg, name, addr))
            .setPositiveButton(R.string.accept) { _, _ -> future.complete(true) }
            .setNegativeButton(R.string.deny) { _, _ -> future.complete(false) }
            .setOnCancelListener { future.complete(false) }
            .show()
    }

    private fun updateUi() {
        btnStart.isEnabled = !sharing
        btnStop.isEnabled = sharing
        if (!sharing) {
            tvStatus.text = getString(R.string.host_status)
        } else {
            val ip = HostService.localIp() ?: "IP گوشی"
            tvStatus.text = getString(R.string.host_active, ip, Proto.PORT)
        }
    }

    override fun onStart() {
        super.onStart()
        updateUi()
        // به‌روزرسانی وضعیت هر ثانیه
        val ticker = object : Runnable {
            override fun run() {
                if (sharing) {
                    val ip = HostService.localIp() ?: "IP گوشی"
                    val base = getString(R.string.host_active, ip, Proto.PORT)
                    tvStatus.text = "$base\n${HostState.statusText}"
                }
                ui.postDelayed(this, 1000)
            }
        }
        ui.post(ticker)
        HostState.setApprovalListener { name, addr, future ->
            runOnUiThread { showApprovalDialog(name, addr, future) }
        }
    }

    override fun onStop() {
        super.onStop()
        // پس از خروج اکتیویتی، درخواست‌های جدید به‌صورت خودکار رد می‌شوند
        if (!sharing) HostState.setApprovalListener(null)
    }

    override fun onDestroy() {
        super.onDestroy()
        if (!sharing) HostState.setApprovalListener(null)
    }
}
