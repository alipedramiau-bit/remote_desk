package com.remotedesk.app

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity

/**
 * صفحه اصلی — انتخاب نقش: نمایشگر (کنترل رایانه) یا میزبان (اشتراک صفحه گوشی).
 */
class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        findViewById<Button>(R.id.btnRoleViewer).setOnClickListener {
            startActivity(Intent(this, ViewerActivity::class.java))
        }
        findViewById<Button>(R.id.btnRoleHost).setOnClickListener {
            startActivity(Intent(this, HostActivity::class.java))
        }
    }
}
