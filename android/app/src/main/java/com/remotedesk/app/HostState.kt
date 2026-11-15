package com.remotedesk.app

import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit

/**
 * وضعیت مشترک بین HostService و HostActivity.
 */
object HostState {
    @Volatile var pin: String = "000000"
    @Volatile var approvalRequired: Boolean = true
    @Volatile var running: Boolean = false
    @Volatile var statusText: String = "غیرفعال"

    // لیسنر تائید اتصال؛ اگر null باشد درخواست‌ها رد می‌شوند
    @Volatile private var listener: ((name: String, addr: String, future: CompletableFuture<Boolean>) -> Unit)? = null

    fun setApprovalListener(l: ((String, String, CompletableFuture<Boolean>) -> Unit)?) {
        listener = l
    }

    /** از نخ شبکه صدا زده می‌شود؛ تا ۴۵ ثانیه منتظر تصمیم کاربر می‌ماند. */
    fun requestApproval(name: String, addr: String): Boolean {
        val l = listener ?: return false
        val future = CompletableFuture<Boolean>()
        try {
            l(name, addr, future)
        } catch (e: Exception) {
            return false
        }
        return try {
            future.get(45, TimeUnit.SECONDS)
        } catch (e: Exception) {
            false
        }
    }
}
