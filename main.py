import sys
import math
import asyncio
import threading

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSlider,
    QSystemTrayIcon, QMenu, QLabel, QPushButton
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QConicalGradient,
    QIcon, QPixmap, QAction, QLinearGradient, QImage
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QObject, QTimer

from bleak import BleakScanner, BleakClient


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
        self.resize(520, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.wheel = ColorWheel()
        layout.addWidget(self.wheel, stretch=1)

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

        # Connection status label
        self.conn_label = QLabel("Connecting...")
        self.conn_label.setStyleSheet("color: #ffaa00; font-size: 13px; font-weight: bold;")
        self.conn_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.conn_label)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #888; font-size: 12px;")
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

        self.ble.status.connect(self.status.setText)
        self.ble.connected.connect(self._on_connection)

    def _on_color_changed(self, r, g, b):
        self._pending_rgb = (r, g, b)
        self._color_timer.start()

    def _on_brightness_changed(self, v):
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
    app = App(sys.argv)
    sys.exit(app.exec())
