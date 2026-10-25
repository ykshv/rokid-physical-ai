package io.github.ykshv.rokidphysicalai

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.audiofx.AcousticEchoCanceler
import android.os.Bundle
import android.util.Base64
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var hud: GlassesHud
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setTurnScreenOn(true)
        hud = GlassesHud(this)
        setContentView(hud)
        hud.show("Подключение…")
        if (intent.getBooleanExtra("diagnostics_only", false)) {
            val manager = getSystemService(CameraManager::class.java)
            for (id in manager.cameraIdList) {
                val c = manager.getCameraCharacteristics(id)
                val sizes = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                    ?.getOutputSizes(android.graphics.ImageFormat.YUV_420_888)?.joinToString()
                Log.i("RokidPhysicalAI", "camera=$id yuv=$sizes orientation=" +
                    c.get(CameraCharacteristics.SENSOR_ORIENTATION))
            }
            Log.i("RokidPhysicalAI", "aec_available=${AcousticEchoCanceler.isAvailable()}")
            return // Capability inspection never starts capture.
        }
        requestSession()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (!intent.getBooleanExtra("diagnostics_only", false)) requestSession()
    }

    private fun requestSession() {
        val identity = try { Identity.load(this) } catch (error: Exception) {
            Log.e("RokidPhysicalAI", "identity_unavailable ${error.javaClass.simpleName}")
            null
        }
        if (identity == null) {
            HudState.publish("Нужно подключение", "Настройте сопряжение на ПК")
            return
        }
        val permissions = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (permissions.any { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED })
            requestPermissions(permissions, 1)
        else startForegroundService(Intent(this, CaptureService::class.java))
    }

    override fun onResume() {
        super.onResume()
        HudState.observer = { hud.show(HudState.status, HudState.hint) }
        HudState.observer?.invoke()
    }

    override fun onPause() {
        HudState.observer = null
        super.onPause()
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (results.size == 2 && results.all { it == PackageManager.PERMISSION_GRANTED })
            startForegroundService(Intent(this, CaptureService::class.java))
    }
}

class ProvisionActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val view = GlassesHud(this).apply { show("Сопряжение…") }
        setContentView(view)
        val payload = intent.getStringExtra("provision") ?: return finish()
        Thread {
            try {
                val config = JSONObject(String(Base64.decode(payload, Base64.URL_SAFE)))
                val endpoint = config.getString("endpoint")
                require(endpoint.startsWith("https://"))
                val client = Identity.client(config.getString("pin"))
                val request = Request.Builder().url("$endpoint/v1/pair")
                    .post(JSONObject().put("code", config.getString("code")).toString()
                        .toRequestBody("application/json".toMediaType())).build()
                client.newCall(request).execute().use { response ->
                    check(response.isSuccessful) { "pairing_rejected" }
                    val identity = JSONObject(response.body!!.string())
                        .put("endpoint", endpoint).put("pin", config.getString("pin"))
                    Identity.save(this, identity)
                }
                client.dispatcher.executorService.shutdown()
                client.connectionPool.evictAll()
                runOnUiThread { view.show("Подключено", "Можно открыть Physical AI") }
                Log.i("RokidPhysicalAI", "pairing_success")
            } catch (error: Exception) {
                Log.e("RokidPhysicalAI", "pairing_failed ${error.javaClass.simpleName}")
                runOnUiThread { view.show("Нет подключения", "Проверьте настройку на ПК") }
            }
        }.start()
    }
}
