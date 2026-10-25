package io.github.ykshv.rokidphysicalai

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.hardware.camera2.*
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Size
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean

class CameraCapture(private val context: Context, private val deliver: (ByteArray) -> Unit,
                    private val fail: (String) -> Unit) : AutoCloseable {
    private val thread = HandlerThread("camera").apply { start() }
    private val handler = Handler(thread.looper)
    private var camera: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var lastFrame = 0L
    private val closed = AtomicBoolean(false)

    @SuppressLint("MissingPermission")
    fun start() {
        val manager = context.getSystemService(CameraManager::class.java)
        val id = manager.cameraIdList.firstOrNull { cameraId ->
            manager.getCameraCharacteristics(cameraId)
                .get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                ?.getOutputSizes(ImageFormat.YUV_420_888)?.contains(Size(640, 480)) == true
        } ?: throw IllegalStateException("No 640x480 YUV stream")
        reader = ImageReader.newInstance(640, 480, ImageFormat.YUV_420_888, 2).also { r ->
            r.setOnImageAvailableListener({ source ->
                if (closed.get()) return@setOnImageAvailableListener
                source.acquireLatestImage()?.use { image ->
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastFrame < 200) return@use
                    lastFrame = now
                    try {
                        val nv21 = ByteArray(640 * 480 * 3 / 2)
                        for (planeIndex in 0..2) {
                            val p = image.planes[planeIndex]
                            val width = if (planeIndex == 0) 640 else 320
                            val height = if (planeIndex == 0) 480 else 240
                            for (y in 0 until height) for (x in 0 until width) {
                                val dest = if (planeIndex == 0) y * 640 + x
                                    else 640 * 480 + y * 640 + x * 2 + if (planeIndex == 2) 0 else 1
                                nv21[dest] = p.buffer.get(y * p.rowStride + x * p.pixelStride)
                            }
                        }
                        val out = ByteArrayOutputStream()
                        check(YuvImage(nv21, ImageFormat.NV21, 640, 480, null)
                            .compressToJpeg(Rect(0, 0, 640, 480), 75, out))
                        // Calibration uses sensor coordinates; do not guess a phone display rotation.
                        deliver(out.toByteArray())
                    } catch (error: Exception) { fail("camera_encoding_failed") }
                }
            }, handler)
        }
        manager.openCamera(id, object : CameraDevice.StateCallback() {
            override fun onOpened(device: CameraDevice) {
                if (closed.get()) { device.close(); return }
                camera = device
                device.createCaptureSession(listOf(reader!!.surface),
                    object : CameraCaptureSession.StateCallback() {
                        override fun onConfigured(s: CameraCaptureSession) {
                            if (closed.get()) { s.close(); return }
                            session = s
                            val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
                                .apply { addTarget(reader!!.surface) }.build()
                            s.setRepeatingRequest(request, null, handler)
                        }
                        override fun onConfigureFailed(s: CameraCaptureSession) { fail("camera_config_failed") }
                    }, handler)
            }
            override fun onDisconnected(device: CameraDevice) { device.close(); fail("camera_disconnected") }
            override fun onError(device: CameraDevice, error: Int) { device.close(); fail("camera_error_$error") }
        }, handler)
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        // Serialize teardown with onOpened/onConfigured on the camera looper.
        handler.post {
            session?.close(); camera?.close(); reader?.close(); thread.quitSafely()
        }
    }
}
