import sys
import math
import asyncio
import threading

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSlider,
    QSystemTrayIcon, QMenu, QLabel, QPushButton, QGridLayout, QButtonGroup
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QConicalGradient,
    QIcon, QPixmap, QAction, QLinearGradient, QImage
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QObject, QTimer, QSize

from bleak import BleakScanner, BleakClient

_SD_OK = False
_SD_ERR = None
try:
    import sounddevice as sd
    import numpy as np
    try:
        sd.query_devices()
        _SD_OK = True
    except Exception as e:
        _SD_ERR = f"PortAudio not working: {e}"
except OSError as e:
    _SD_ERR = (
        f"System library PortAudio not found: {e}\n"
        "Install: sudo apt install libportaudio2 portaudio19-dev"
    )
except ImportError as e:
    _SD_ERR = (
        f"Python module sounddevice or numpy not installed: {e}\n"
        "Install: pip install sounddevice numpy"
    )
except Exception as e:
    _SD_ERR = f"Unknown error while importing audio: {e}"


CHARACTERISTIC_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
LED_MAC = "BE:27:9D:00:6E:40"


def _cmd_on():
    return [0x7e, 0x07, 0x04, 0xff, 0x00, 0x01, 0x02, 0x01, 0xef]


def _cmd_off():
    return [0x7e, 0x07, 0x04, 0x00, 0x00, 0x00, 0x02, 0x01, 0xef]


def _cmd_color(r, g, b):
    return [0x7e, 0x07, 0x05, 0x03, r, g, b, 0x10, 0xef]


def _cmd_brightness(level):
    level = max(0, min(100, int(level)))
    return [0x7e, 0x04, 0x01, level, 0x01, 0xff, 0x02, 0x01, 0xef]


class BLEWorker(QObject):
    status = pyqtSignal(str)
    connected = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._loop = None
        self._thread = None
        self._client = None
        self._queue = None

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._main_loop())
        finally:
            self._loop.close()

    async def _main_loop(self):
        while True:
            await self._try_connect()
            await asyncio.sleep(5.0)

    async def _try_connect(self):
        try:
            device = await BleakScanner.find_device_by_address(LED_MAC, timeout=10.0)
        except Exception:
            return

        if not device:
            return

        try:
            async with BleakClient(device) as client:
                self._client = client
                self.connected.emit(True)

                await client.write_gatt_char(
                    CHARACTERISTIC_UUID, bytes(_cmd_on())
                )

                while client.is_connected:
                    try:
                        cmd = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        await client.write_gatt_char(
                            CHARACTERISTIC_UUID, bytes(cmd)
                        )
                    except Exception:
                        break
        except Exception:
            pass
        finally:
            self._client = None
            self.connected.emit(False)

    def send(self, cmd_bytes):
        if self._loop is None or self._queue is None:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, cmd_bytes)

    def send_on(self):
        self.send(_cmd_on())

    def send_off(self):
        self.send(_cmd_off())

    def send_color(self, r, g, b):
        self.send(_cmd_color(r, g, b))

    def send_brightness(self, level):
        self.send(_cmd_brightness(level))


class MicLevelWorker(QObject):
    levelChanged = pyqtSignal(float)

    def __init__(self, samplerate=44100, blocksize=1024):
        super().__init__()
        self._samplerate = samplerate
        self._blocksize = blocksize
        self._running = False
        self._thread = None
        self._stream = None
        self._smooth = 0.0
        self._noise_floor = 0.005
        self._gain = 60.0

    @staticmethod
    def available():
        return _SD_OK

    @staticmethod
    def error_message():
        return _SD_ERR

    def start(self):
        if not _SD_OK or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        try:
            def callback(indata, frames, time_info, status):
                if not self._running:
                    return
                if indata.ndim > 1:
                    mono = indata.mean(axis=1)
                else:
                    mono = indata
                rms = float(np.sqrt(np.mean(mono * mono)))

                if rms < self._noise_floor:
                    self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms
                else:
                    self._noise_floor = 0.999 * self._noise_floor + 0.001 * rms

                x = (rms - self._noise_floor) * self._gain
                if x < 0.0:
                    x = 0.0
                if x > 1.0:
                    x = 1.0

                if x > self._smooth:
                    self._smooth = 0.6 * self._smooth + 0.4 * x
                else:
                    self._smooth = 0.85 * self._smooth + 0.15 * x

                self.levelChanged.emit(self._smooth)

            with sd.InputStream(
                channels=1,
                samplerate=self._samplerate,
                blocksize=self._blocksize,
                callback=callback,
            ):
                while self._running:
                    sd.sleep(50)
        except Exception as e:
            print(f"[MicLevelWorker] Audio stream error: {e}")
            self._running = False


def icon_wheel(size=48):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QConicalGradient(size / 2, size / 2, 90)
    for i in range(0, 361, 15):
        grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QRectF(4, 4, size - 8, size - 8))
    p.setBrush(QColor(32, 32, 32))
    p.drawEllipse(QRectF(size * 0.32, size * 0.32, size * 0.36, size * 0.36))
    p.end()
    return QIcon(pm)


def icon_grid(size=48):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    colors = [
        QColor(255, 0, 0), QColor(255, 255, 0), QColor(0, 255, 0),
        QColor(0, 255, 255), QColor(0, 0, 255), QColor(255, 0, 255),
        QColor(255, 128, 0), QColor(255, 255, 255), QColor(128, 0, 255),
    ]
    pad = 4
    cell = (size - pad * 4) / 3.0
    for i in range(9):
        r, c = divmod(i, 3)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + pad)
        p.setBrush(colors[i])
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(x, y, cell, cell), 3, 3)
    p.end()
    return QIcon(pm)


def icon_mic(size=48):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(230, 230, 230), 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(size * 0.40, size * 0.12, size * 0.20, size * 0.42), 8, 8)
    p.drawArc(QRectF(size * 0.28, size * 0.30, size * 0.44, size * 0.42), 180 * 16, 180 * 16)
    p.drawLine(QPointF(size * 0.5, size * 0.72), QPointF(size * 0.5, size * 0.86))
    p.drawLine(QPointF(size * 0.36, size * 0.86), QPointF(size * 0.64, size * 0.86))
    p.end()
    return QIcon(pm)


def icon_gradient(size=48):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(4, size / 2, size - 4, size / 2)
    grad.setColorAt(0.0, QColor(255, 0, 0))
    grad.setColorAt(0.25, QColor(255, 255, 0))
    grad.setColorAt(0.5, QColor(0, 255, 0))
    grad.setColorAt(0.75, QColor(0, 200, 255))
    grad.setColorAt(1.0, QColor(160, 0, 255))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(4, size * 0.25, size - 8, size * 0.5), 6, 6)
    p.end()
    return QIcon(pm)


class ModeButton(QPushButton):
    def __init__(self, icon, tooltip):
        super().__init__()
        self.setIcon(icon)
        self.setIconSize(QSize(28, 28))
        self.setCheckable(True)
        self.setFixedHeight(46)
        self.setToolTip(tooltip)
        self.setStyleSheet(
            "QPushButton { background:#2a2a2a; border:1px solid #3a3a3a; "
            "border-radius:8px; }"
            "QPushButton:hover { background:#383838; }"
            "QPushButton:checked { background:#3d5a80; border:1px solid #6ea8ff; }"
        )


class ColorWheel(QWidget):
    colorChanged = pyqtSignal(int, int, int)

    def __init__(self):
        super().__init__()
        self.hue = 0.0
        self.value = 1.0
        self.rgb = (255, 255, 255)
        self._dragging = False
        self._wheel_img = None
        self._wheel_img_size = 0
        self._wheel_img_value = -1.0

    def _build_wheel_image(self, size):
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        cx = cy = size / 2.0
        outer = size / 2.0
        inner = outer * 0.75
        v = self.value
        for y in range(size):
            dy = y + 0.5 - cy
            for x in range(size):
                dx = x + 0.5 - cx
                r = math.hypot(dx, dy)
                if r > outer or r < inner:
                    continue
                hue = math.degrees(math.atan2(dx, -dy)) % 360.0
                c = QColor.fromHsvF(hue / 360.0, 1.0, v)
                img.setPixelColor(x, y, c)
        return img

    def _ensure_wheel_image(self):
        size = int(min(self.width(), self.height()))
        if size <= 0:
            return
        if (self._wheel_img is None
                or self._wheel_img_size != size
                or abs(self._wheel_img_value - self.value) > 1e-3):
            self._wheel_img = self._build_wheel_image(size)
            self._wheel_img_size = size
            self._wheel_img_value = self.value

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        outer = min(self.width(), self.height()) / 2 - 20
        inner = outer * 0.75
        mid_r = (outer + inner) / 2

        self._ensure_wheel_image()
        if self._wheel_img is not None:
            img_size = self._wheel_img_size
            target = outer * 2
            scale = target / img_size
            p.save()
            p.translate(cx, cy)
            p.scale(scale, scale)
            p.drawImage(QPointF(-img_size / 2, -img_size / 2), self._wheel_img)
            p.restore()

        color = QColor(*self.rgb)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(cx, cy), inner * 0.55, inner * 0.55)

        p.setPen(QColor(0, 0, 0) if sum(self.rgb) > 380 else QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(max(8, int(inner * 0.13)))
        font.setBold(True)
        p.setFont(font)
        text = f"{self.rgb[0]}, {self.rgb[1]}, {self.rgb[2]}"
        p.drawText(QRectF(cx - inner, cy - 30, inner * 2, 60),
                   Qt.AlignmentFlag.AlignCenter, text)

        ang = math.radians(self.hue)
        px = cx + mid_r * math.sin(ang)
        py = cy - mid_r * math.cos(ang)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0), 3))
        p.drawEllipse(QPointF(px, py), 12, 12)
        p.setPen(QPen(QColor(255, 255, 255), 3))
        p.drawEllipse(QPointF(px, py), 9, 9)

    def mousePressEvent(self, event):
        self._dragging = True
        self._update(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update(event.position())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _update(self, pos):
        cx = self.width() / 2
        cy = self.height() / 2
        dx = pos.x() - cx
        dy = pos.y() - cy
        hue = math.degrees(math.atan2(dx, -dy)) % 360.0
        self.hue = hue
        self._recalc()

    def set_value(self, v):
        self.value = v
        self._recalc()

    def set_rgb_external(self, r, g, b):
        c = QColor(r, g, b)
        h, s, v, _ = c.getHsvF()
        self.hue = (h * 360.0) if h >= 0 else 0.0
        self.value = max(0.0, min(1.0, v))
        self.rgb = (r, g, b)
        self.update()

    def _recalc(self):
        color = QColor.fromHsvF((self.hue % 360) / 360.0, 1.0, self.value)
        self.rgb = (color.red(), color.green(), color.blue())
        self.update()
        self.colorChanged.emit(*self.rgb)


class BrightnessSlider(QSlider):
    def __init__(self, wheel):
        super().__init__(Qt.Orientation.Horizontal)
        self.wheel = wheel
        self.setRange(0, 100)
        self.setValue(100)
        self.setFixedHeight(30)
        self.valueChanged.connect(self._on_change)

    def _on_change(self, v):
        self.wheel.set_value(v / 100.0)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = QColor.fromHsvF((self.wheel.hue % 360) / 360.0, 1.0, 1.0)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor(0, 0, 0))
        grad.setColorAt(1.0, base)
        rect = QRectF(4, 8, self.width() - 8, self.height() - 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, 4, 4)
        ratio = self.value() / self.maximum()
        hx = rect.left() + ratio * rect.width()
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(0, 0, 0), 2))
        p.drawEllipse(QPointF(hx, self.height() / 2), 9, 9)


class PickerWindow(QWidget):
    def __init__(self, ble: BLEWorker, tray_icon=None):
        super().__init__()
        self.ble = ble
        self.tray_icon = tray_icon
        self.setWindowTitle("LED Color Picker by vad5m_dev")
        self.setStyleSheet("background-color: #202020;")
        self.resize(520, 800)

        self.mode = "wheel"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.wheel = ColorWheel()
        layout.addWidget(self.wheel, stretch=1)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        self.btn_mode_wheel = ModeButton(icon_wheel(), "Color wheel")
        self.btn_mode_grid = ModeButton(icon_grid(), "9-color palette")
        self.btn_mode_mic = ModeButton(icon_mic(), "Microphone: color from wheel, brightness from volume")
        self.btn_mode_gradient = ModeButton(icon_gradient(), "Rainbow gradient")

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for b in (self.btn_mode_wheel, self.btn_mode_grid,
                  self.btn_mode_mic, self.btn_mode_gradient):
            self.mode_group.addButton(b)
            mode_row.addWidget(b)

        self.btn_mode_wheel.setChecked(True)
        self.btn_mode_wheel.clicked.connect(lambda: self.set_mode("wheel"))
        self.btn_mode_grid.clicked.connect(lambda: self.set_mode("grid"))
        self.btn_mode_mic.clicked.connect(lambda: self.set_mode("mic"))
        self.btn_mode_gradient.clicked.connect(lambda: self.set_mode("gradient"))

        layout.addLayout(mode_row)

        self.grid_widget = QWidget()
        grid = QGridLayout(self.grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self._grid_colors = [
            (255, 0, 0), (255, 165, 0), (255, 255, 0),
            (0, 255, 0), (0, 255, 255), (0, 0, 255),
            (128, 0, 255), (255, 0, 255), (255, 255, 255),
        ]
        for i, (r, g, b) in enumerate(self._grid_colors):
            rr, cc = divmod(i, 3)
            btn = QPushButton()
            btn.setFixedHeight(52)
            btn.setStyleSheet(
                f"QPushButton {{ background: rgb({r},{g},{b}); "
                f"border:1px solid #444; border-radius:8px; }}"
                f"QPushButton:hover {{ border:2px solid #fff; }}"
            )
            btn.clicked.connect(lambda _=False, r=r, g=g, b=b: self._apply_grid_color(r, g, b))
            grid.addWidget(btn, rr, cc)
        self.grid_widget.setVisible(False)
        layout.addWidget(self.grid_widget)

        row = QHBoxLayout()
        lbl = QLabel("Brightness:")
        lbl.setStyleSheet("color: #ddd; font-size: 14px;")
        lbl.setFixedWidth(80)
        self.slider = BrightnessSlider(self.wheel)
        row.addWidget(lbl)
        row.addWidget(self.slider, stretch=1)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.btn_on = QPushButton("Turn On")
        self.btn_off = QPushButton("Turn Off")
        for b in (self.btn_on, self.btn_off):
            b.setStyleSheet(
                "QPushButton { background:#333; color:#eee; padding:8px; "
                "border-radius:6px; font-size:14px; }"
                "QPushButton:hover { background:#444; }"
                "QPushButton:disabled { background:#222; color:#666; }"
            )
        self.btn_on.clicked.connect(self.ble.send_on)
        self.btn_off.clicked.connect(self.ble.send_off)
        btn_row.addWidget(self.btn_on)
        btn_row.addWidget(self.btn_off)
        layout.addLayout(btn_row)

        self.conn_label = QLabel("Connecting...")
        self.conn_label.setStyleSheet("color: #ffaa00; font-size: 13px; font-weight: bold;")
        self.conn_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.conn_label)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #888; font-size: 12px;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self._color_timer = QTimer(self)
        self._color_timer.setSingleShot(True)
        self._color_timer.setInterval(80)
        self._color_timer.timeout.connect(self._flush_color)

        self._bright_timer = QTimer(self)
        self._bright_timer.setSingleShot(True)
        self._bright_timer.setInterval(80)
        self._bright_timer.timeout.connect(self._flush_brightness)

        self._pending_rgb = (255, 255, 255)
        self._pending_brightness = 100

        self.wheel.colorChanged.connect(self._on_color_changed)
        self.slider.valueChanged.connect(self._on_brightness_changed)

        self._gradient_timer = QTimer(self)
        self._gradient_timer.setInterval(60)
        self._gradient_timer.timeout.connect(self._tick_gradient)
        self._gradient_hue = 0.0

        self.mic = MicLevelWorker()
        self.mic.levelChanged.connect(self._on_mic_level)
        if MicLevelWorker.available():
            self.mic.start()
            print("[MicLevelWorker] Microphone started")
        else:
            print(f"[MicLevelWorker] Microphone unavailable:\n{MicLevelWorker.error_message()}")

        self._mic_min_brightness = 5
        self._mic_max_brightness = 100
        self._mic_bright_smooth = 0.0

        self.ble.status.connect(self.status.setText)
        self.ble.connected.connect(self._on_connection)

    def set_mode(self, mode: str):
        self.mode = mode
        self.grid_widget.setVisible(mode == "grid")
        self._gradient_timer.stop()

        if mode == "gradient":
            self._gradient_timer.start()
        elif mode == "mic":
            if not MicLevelWorker.available():
                self.status.setText(
                    f"Microphone unavailable.\n{MicLevelWorker.error_message()}"
                )
            else:
                self.status.setText("Microphone mode active")

    def _apply_grid_color(self, r, g, b):
        self.wheel.set_rgb_external(r, g, b)
        self._pending_rgb = (r, g, b)
        self.ble.send_color(r, g, b)

    def _tick_gradient(self):
        self._gradient_hue = (self._gradient_hue + 4.0) % 360.0
        c = QColor.fromHsvF(self._gradient_hue / 360.0, 1.0, 1.0)
        r, g, b = c.red(), c.green(), c.blue()
        self.wheel.set_rgb_external(r, g, b)
        self.ble.send_color(r, g, b)

    def _on_mic_level(self, level: float):
        if self.mode != "mic":
            return
        target = self._mic_min_brightness + level * (
            self._mic_max_brightness - self._mic_min_brightness
        )
        if target > self._mic_bright_smooth:
            self._mic_bright_smooth = 0.5 * self._mic_bright_smooth + 0.5 * target
        else:
            self._mic_bright_smooth = 0.8 * self._mic_bright_smooth + 0.2 * target
        v = int(max(0, min(100, self._mic_bright_smooth)))
        if v != self.slider.value():
            self.slider.setValue(v)
        self.ble.send_brightness(v)

    def _on_color_changed(self, r, g, b):
        self._pending_rgb = (r, g, b)
        self._color_timer.start()

    def _on_brightness_changed(self, v):
        if self.mode == "mic":
            return
        self._pending_brightness = v
        self._bright_timer.start()

    def _flush_color(self):
        r, g, b = self._pending_rgb
        self.ble.send_color(r, g, b)

    def _flush_brightness(self):
        self.ble.send_brightness(self._pending_brightness)

    def _on_connection(self, ok: bool):
        self.btn_on.setEnabled(ok)
        self.btn_off.setEnabled(ok)
        if ok:
            self.conn_label.setText("Connected")
            self.conn_label.setStyleSheet("color: #44dd44; font-size: 13px; font-weight: bold;")
        else:
            self.conn_label.setText("Reconnecting...")
            self.conn_label.setStyleSheet("color: #ffaa00; font-size: 13px; font-weight: bold;")

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if self.tray_icon:
            self.tray_icon.showMessage(
                "LED Color Picker",
                "Minimized to tray. Click the icon to open.",
                QSystemTrayIcon.MessageIcon.Information,
                1500,
            )


def make_tray_icon_pixmap():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    grad = QConicalGradient(32, 32, 90)
    for i in range(0, 361, 15):
        grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QRectF(4, 4, 56, 56))
    p.setBrush(QColor(0, 0, 0, 0))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawEllipse(QRectF(18, 18, 28, 28))
    p.end()
    return pm


class App(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)

        self.ble = BLEWorker()
        self.ble.start()

        self.tray = QSystemTrayIcon(QIcon(make_tray_icon_pixmap()), self)
        self.tray.setToolTip("LED Color Picker")

        menu = QMenu()
        act_show = QAction("Open", self)
        act_show.triggered.connect(self.show_window)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_click)

        self.window = PickerWindow(ble=self.ble, tray_icon=self.tray)
        self.tray.show()

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()


if __name__ == "__main__":
    ascii = """
    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣶⣶⠀⠀⠀⠀
    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⠀⢸⣄⠀⠀
    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⢰⠛⠀⠀⠹⣧⠀⠀
    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⠀⠀⠀⠀⣿⠀⠀
    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⢠⠀⡄⠀⣿⠀⢀⣤⣤⠀⠀⠀
    ⠀⠀⠀⠀⠀⠀⠀⠀⢰⡏⠚⠀⠃⠀⣿⣴⠞⠉⢹⠀⠀⠀
    ⠀⣀⡀⠀⠀⠀⠀⢀⣸⠇⠀⠀⠀⠀⠈⠀⠀⣀⡿⠀⠀⠀
    ⢸⣟⠛⢳⣤⣤⡶⠛⠃⠀⣠⠀⠀⠀⠚⣶⡾⠟⠀⠀⠀⠀
    ⠀⠉⢷⣤⣀⣀⣀⣀⣠⡾⠻⣧⡀⠀⠀⢘⣷⣄⣀⣤⣄⠀⠀⠀⠀
    ⠀⠀⠀⠈⠉⠉⠉⠉⠉⠀⠀⠘⠻⣦⣤⣈⣁⣀⣠⣾⠋⠀⠀⠀⠀
    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠉⠉⠉⠉⠀
    """
    print(ascii)

    if MicLevelWorker.available():
        print("[Sound] sounddevice + PortAudio OK")
    else:
        print(f"[Sound] UNAVAILABLE:\n{MicLevelWorker.error_message()}")

    app = App(sys.argv)
    sys.exit(app.exec())
