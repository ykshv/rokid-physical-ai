package io.github.ykshv.rokidphysicalai

import android.annotation.SuppressLint
import android.app.*
import android.content.Intent
import android.media.*
import android.media.audiofx.AcousticEchoCanceler
import android.os.*
import android.util.Base64
import android.util.Log
import okhttp3.*
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.atomic.AtomicBoolean

class CaptureService : Service() {
    private val main = Handler(Looper.getMainLooper())
    private val alive = AtomicBoolean(false)
    private var client: OkHttpClient? = null
    private var control: WebSocket? = null
    private var media: WebSocket? = null
    private var camera: CameraCapture? = null
    private var recorder: AudioRecord? = null
    private var track: AudioTrack? = null
    private var aec: AcousticEchoCanceler? = null
    private var audioManager: AudioManager? = null
    private var focusRequest: AudioFocusRequest? = null
    private var wake: PowerManager.WakeLock? = null
    private data class Chunk(val item: String, val pcm: ByteArray, val preview: String?, val last: Boolean, val generation: Long)
    private val playback = ArrayBlockingQueue<Chunk>(20)
    private val audioLock = Any()
    @Volatile private var generation = 0L
    private var writtenFrames = 0L
    private var recordThread: Thread? = null
    private var playThread: Thread? = null
    @Volatile private var playingItem = ""
    @Volatile private var itemStartHead = 0L

    override fun onBind(intent: Intent?) = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("capture", "Active session", NotificationManager.IMPORTANCE_LOW))
        startForeground(1, Notification.Builder(this, "capture").setContentTitle("Rokid Physical AI")
            .setContentText("Камера и микрофон активны только в рабочей сессии")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now).build())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!alive.compareAndSet(false, true)) return START_NOT_STICKY
        HudState.publish("Подключение…")
        try { connect() } catch (error: Exception) { fail("startup_${error.javaClass.simpleName}") }
        return START_NOT_STICKY
    }

    private fun connect() {
        val identity = Identity.load(this) ?: error("Device not paired")
        val endpoint = identity.getString("endpoint")
        client = Identity.client(identity.getString("pin"))
        fun request(path: String) = Request.Builder().url(endpoint.replaceFirst("https://", "wss://") + path)
            .header("Authorization", "Bearer " + identity.getString("token")).build()
        control = client!!.newWebSocket(request("/v1/control"), object : WebSocketListener() {
            override fun onMessage(ws: WebSocket, text: String) {
                try {
                    val event = JSONObject(text)
                    when (event.getString("type")) {
                        "session.ready" -> {
                            val session = event.getString("session_id")
                            media = client!!.newWebSocket(request("/v1/media/$session"), object : WebSocketListener() {
                                override fun onOpen(ws: WebSocket, response: Response) {
                                    sendControl(JSONObject().put("type", "session.start"))
                                }
                                override fun onMessage(ws: WebSocket, text: String) {
                                    try {
                                        val audio = JSONObject(text)
                                        if (audio.getString("type") == "audio.clear") { clearAudio(); return }
                                        val encoded = audio.getString("audio")
                                        require(encoded.length <= 12800)
                                        val bytes = Base64.decode(encoded, Base64.DEFAULT)
                                        require(bytes.isNotEmpty() && bytes.size % 2 == 0)
                                        val preview = if (audio.isNull("preview_task_id")) null else audio.getString("preview_task_id")
                                        if (!playback.offer(Chunk(audio.getString("item_id"), bytes, preview,
                                                audio.optBoolean("last"), generation))) fail("playback_overflow")
                                    } catch (error: Exception) { fail("invalid_audio") }
                                }
                                override fun onFailure(ws: WebSocket, error: Throwable, response: Response?) { fail("media_connection_failed") }
                                override fun onClosed(ws: WebSocket, code: Int, reason: String) { fail("media_closed") }
                            })
                            main.post(heartbeat)
                        }
                        "session.started" -> main.post {
                            startCapture()
                            if (event.optBoolean("diagnostic")) HudState.publish("Проверка связи", "Камера и микрофон включены")
                            else HudState.publish("Слушаю")
                        }
                        "audio.clear" -> clearAudio()
                        "session.ended" -> main.post { HudState.publish("Сессия завершена"); stopSelf() }
                        "confirmation.result" -> HudState.publish(if (event.optBoolean("accepted")) "Выполняю" else "Нужно повторить команду")
                        "task.result" -> main.post {
                            val message = when (event.getString("state")) {
                                "succeeded" -> "Задача выполнена."
                                "cancelled" -> "Задача отменена."
                                else -> "Выполнение не подтверждено. Проверьте робота."
                            }
                            HudState.publish(message)
                        }
                        "error" -> fail(event.getString("code"))
                    }
                } catch (error: Exception) { fail("invalid_control_event") }
            }
            override fun onFailure(ws: WebSocket, error: Throwable, response: Response?) { fail("control_connection_failed") }
            override fun onClosed(ws: WebSocket, code: Int, reason: String) { fail("control_closed") }
        })
    }

    private val heartbeat = object : Runnable {
        override fun run() {
            if (!alive.get()) return
            sendControl(JSONObject().put("type", "heartbeat"))
            val current = track
            if (current != null && playingItem.isNotEmpty()) {
                val frames = (current.playbackHeadPosition.toLong() and 0xffffffffL) - itemStartHead
                sendControl(JSONObject().put("type", "audio.played").put("item_id", playingItem)
                    .put("milliseconds", (frames.coerceAtLeast(0) * 1000 / 24000)))
            }
            main.postDelayed(this, 500)
        }
    }

    @SuppressLint("MissingPermission")
    private fun startCapture() {
        try {
            val audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
            audioManager = getSystemService(AudioManager::class.java)
            focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
                .setAudioAttributes(audioAttributes).setAcceptsDelayedFocusGain(false)
                .setWillPauseWhenDucked(true)
                .setOnAudioFocusChangeListener({ focus ->
                    if (focus < 0 && alive.get()) fail("audio_focus_lost")
                }, main).build()
            check(audioManager!!.requestAudioFocus(focusRequest!!) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
                "audio_focus_denied"
            }
            wake = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                "RokidPhysicalAI:session").apply { acquire(55 * 60 * 1000L) }
            val format = AudioFormat.Builder().setSampleRate(24000).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(AudioFormat.CHANNEL_IN_MONO).build()
            recorder = AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_COMMUNICATION)
                .setAudioFormat(format).setBufferSizeInBytes(maxOf(9600,
                    AudioRecord.getMinBufferSize(24000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT))).build()
            check(recorder!!.state == AudioRecord.STATE_INITIALIZED)
            aec = AcousticEchoCanceler.create(recorder!!.audioSessionId)?.apply { enabled = true }
            track = AudioTrack.Builder().setAudioAttributes(audioAttributes)
                .setAudioFormat(AudioFormat.Builder().setSampleRate(24000).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                .setBufferSizeInBytes(24000).setTransferMode(AudioTrack.MODE_STREAM).build()
            // Short prompts must start before the default half-second buffer fills.
            track!!.setStartThresholdInFrames(480)
            audioManager!!.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
                .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
                ?.let { check(track!!.setPreferredDevice(it)) }
            audioManager!!.getDevices(AudioManager.GET_DEVICES_INPUTS)
                .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC }
                ?.let { check(recorder!!.setPreferredDevice(it)) }
            track!!.play(); recorder!!.startRecording()
            recordThread = Thread {
                val buffer = ByteArray(960)
                while (alive.get()) {
                    val n = recorder?.read(buffer, 0, buffer.size) ?: break
                    if (n <= 0) { fail("audio_record_failed"); break }
                    if (media?.queueSize() ?: 0 > 256000) { fail("audio_backpressure"); break }
                    if (media?.send(buffer.toByteString(0, n)) != true) { fail("audio_send_failed"); break }
                }
            }.apply { name = "microphone"; start() }
            playThread = Thread {
                try {
                    while (alive.get()) {
                        val chunk = playback.take()
                        var offset = 0
                        while (offset < chunk.pcm.size && alive.get() && chunk.generation == generation) {
                            synchronized(audioLock) {
                                if (chunk.generation == generation && alive.get()) {
                                    if (playingItem != chunk.item) {
                                        playingItem = chunk.item
                                        itemStartHead = writtenFrames
                                    }
                                    val count = track!!.write(chunk.pcm, offset, chunk.pcm.size - offset)
                                    check(count > 0) { "audio_playback_failed" }
                                    offset += count
                                    writtenFrames += count / 2
                                }
                            }
                        }
                        if (chunk.last) {
                            val end = writtenFrames
                            val deadline = SystemClock.elapsedRealtime() + 3000
                            while (alive.get() && chunk.generation == generation &&
                                    (track!!.playbackHeadPosition.toLong() and 0xffffffffL) < end) {
                                check(SystemClock.elapsedRealtime() < deadline) { "audio_playback_timeout" }
                                Thread.sleep(20)
                            }
                            if (alive.get() && chunk.generation == generation) {
                                Log.i("RokidPhysicalAI", "playback_completed frames=$end")
                                if (chunk.preview != null) {
                                    sendControl(JSONObject().put("type", "preview.played").put("task_id", chunk.preview))
                                    HudState.publish("Подтвердите голосом", "Скажите: подтверждаю")
                                }
                            }
                        }
                    }
                } catch (_: InterruptedException) { /* Session shutdown interrupts the bounded queue. */ }
                catch (error: Exception) { if (alive.get()) fail("speaker_${error.javaClass.simpleName}") }
            }.apply { name = "speaker"; start() }
            camera = CameraCapture(this, { jpeg ->
                if (alive.get() && (media?.queueSize() ?: Long.MAX_VALUE) < 48000) {
                    media?.send(JSONObject().put("type", "frame").put("id", "f_" + UUID.randomUUID().toString().replace("-", ""))
                        .put("jpeg", Base64.encodeToString(jpeg, Base64.NO_WRAP)).toString())
                }
            }, ::fail).also { it.start() }
            sendControl(JSONObject().put("type", "diagnostics").put("camera", "640x480-YUV")
                .put("aec", aec?.enabled == true).put("tts_ru", false))
            Log.i("RokidPhysicalAI", "capture_started")
        } catch (error: Exception) { fail("capture_${error.javaClass.simpleName}") }
    }

    private fun sendControl(event: JSONObject) { control?.send(event.toString()) }
    private fun clearAudio() {
        synchronized(audioLock) {
            generation++
            playback.clear()
            track?.let { it.pause(); it.flush(); if (alive.get()) it.play() }
            playingItem = ""
            writtenFrames = 0
            itemStartHead = 0
        }
    }
    private fun fail(code: String) {
        if (!alive.get()) return
        Log.e("RokidPhysicalAI", code)
        HudState.publish("Сессия остановлена", "Проверьте связь с ПК")
        main.post { stopSelf() }
    }

    override fun onDestroy() {
        alive.set(false)
        main.removeCallbacks(heartbeat)
        sendControl(JSONObject().put("type", "session.stop"))
        camera?.close()
        if (recorder?.recordingState == AudioRecord.RECORDSTATE_RECORDING) recorder?.stop()
        clearAudio()
        recordThread?.join(1000)
        playThread?.interrupt(); playThread?.join(1000)
        recorder?.release(); track?.release(); aec?.release()
        focusRequest?.let { audioManager?.abandonAudioFocusRequest(it) }
        media?.close(1000, "session_end"); control?.close(1000, "session_end")
        client?.dispatcher?.executorService?.shutdown(); client?.connectionPool?.evictAll()
        if (wake?.isHeld == true) wake?.release()
        Log.i("RokidPhysicalAI", "capture_stopped")
        super.onDestroy()
    }
}
