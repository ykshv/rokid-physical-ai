package io.github.ykshv.rokidphysicalai

import android.app.Activity
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/** Black is optically transparent. Pixel sizes intentionally bypass phone density scaling. */
class GlassesHud(activity: Activity) : FrameLayout(activity) {
    private val title = TextView(activity)
    private val detail = TextView(activity)

    init {
        setBackgroundColor(Color.BLACK)
        activity.window.setBackgroundDrawableResource(android.R.color.black)
        activity.window.setDecorFitsSystemWindows(false)
        activity.window.decorView.post {
            activity.window.insetsController?.apply {
                hide(WindowInsets.Type.systemBars())
                systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        }
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val content = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
        }
        // Keep the entire HUD in the central 480x352 reference area; no illuminated panel.
        addView(content, LayoutParams(416, 120, Gravity.CENTER))
        title.apply {
            setTextColor(Color.rgb(0, 210, 0))
            setTextSize(TypedValue.COMPLEX_UNIT_PX, 26f)
            gravity = Gravity.CENTER
            maxLines = 2
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        detail.apply {
            setTextColor(Color.rgb(0, 155, 0))
            setTextSize(TypedValue.COMPLEX_UNIT_PX, 18f)
            gravity = Gravity.CENTER
            maxLines = 2
            setPadding(0, 12, 0, 0)
        }
        content.addView(title)
        content.addView(detail)
    }

    fun show(status: String, hint: String = "") {
        title.text = status
        detail.text = hint
        detail.visibility = if (hint.isEmpty()) View.GONE else View.VISIBLE
    }
}

/** Process-local state only; external apps cannot impersonate session status. */
object HudState {
    private val main = Handler(Looper.getMainLooper())
    var status = "Подключение…"
        private set
    var hint = ""
        private set
    var observer: (() -> Unit)? = null
    fun publish(text: String, detail: String = "") {
        main.post {
            status = text
            hint = detail
            observer?.invoke()
        }
    }
}
