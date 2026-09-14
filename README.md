# LED-color-picker


<img width="591" height="782" alt="изображение" src="https://github.com/user-attachments/assets/9bab2e9e-24a9-4898-91f8-7eb6722f8101" />


# LED Color Picker

This is a simple desktop application written in Python using PyQt6 for controlling a BLE LED strip. The app lets you pick a color with an interactive color wheel, adjust brightness, and control power. It runs in the system tray.

## ✨ Features

- **Color Wheel** — interactive color selection with RGB value display
- **Brightness Control** — slider with a gradient visualization from black to the selected color
- **Power Control** — buttons to turn the strip on and off
- **Bluetooth Low Energy** — automatic discovery and connection to the device by MAC address
- **System Tray** — minimizes to tray with notifications, runs in the background
- **Asynchronous Command Sending** — a separate thread with a queue for the BLE connection
- **Input Debouncing** — delay timers to reduce the number of commands sent

## 📋 Requirements

- **Python 3.8+**
- **PyQt6**
- **bleak** (asynchronous BLE library)

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/vad5m/LED-color-picker.git
cd led-color-picker
```

### 2. Install dependencies
```bash
pip install PyQt6 bleak sounddevice numpy
sudo apt install libportaudio2 portaudio19-dev
```

### 3. Configure the device MAC address

In `main.py`, find the constant:
```python
LED_MAC = "BE:27:9D:00:6E:40"
```

This is the MAC address of your BLE strip. **You need to replace it with your device's address.**

#### 🔍 How to find the MAC address using `bluetoothctl`

1. Launch the utility:
   ```bash
   bluetoothctl
   ```

2. Enable scanning:
   ```
   scan on
   ```

3. Wait for the device list to appear. Find your strip (usually the name contains `LED`, `ELK`, `Triones`, `LEDBlue`, or similar):
   ```
   [NEW] Device BE:27:9D:00:6E:40 ELK-BLEDDM
   [NEW] Device AA:BB:CC:DD:EE:FF SomeOtherDevice
   ```

4. Copy the MAC address (in the example above — `BE:27:9D:00:6E:40`) and stop scanning:
   ```
   scan off
   exit
   ```

5. Paste the address into the code:
   ```python
   LED_MAC = "BE:27:9D:00:6E:40"  # ← replace with your own
   ```

> 💡 **Tip:** if the address doesn't show up, make sure the strip is powered on, nearby, and not already connected to another device (e.g., a phone app).

## 🎮 Usage

### Quick Start
```bash
python3 main.py
```

The app starts, searches for the device, and connects automatically.

### Controls

| Action | Description |
|--------|-------------|
| **Click on the color wheel** | Select a color (hue) |
| **Brightness slider** | Adjust brightness (0–100) |
| **Turn On** | Turn the strip on |
| **Turn Off** | Turn the strip off |
| **Tray icon** | Open the window or quit the app |

### What You Can Configure
- **Color** — hue is selected on the wheel, brightness on the slider
- **Brightness** — from 0 to 100%
- **Power** — turn the strip on and off

## 🗂️ Project Structure

```
led-color-picker/
├── main.py              # Main application file
└── README.md
```


 <pre>
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣄⢘⣒⣀⣀⣀⣀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣽⣿⣛⠛⢛⣿⣿⡿⠟⠂⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⣀⣀⡀⠀⣤⣾⣿⣿⣿⣿⣿⣿⣿⣷⣿⡆⠀
⠀⠀⠀⠀⠀⠀⣀⣤⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠁⠀
⠀⠀⠀⢀⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀
⠀⠀⣠⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀
⠀⠀⠻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠟⠜⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⢿⣿⣿⣿⣿⠿⠿⣿⣿⡿⢿⣿⣿⠈⣿⣿⣿⡏⣠⡴⠀⠀⠀⠀⠀⠀⠀
⠀⠀⣠⣿⣿⣿⡿⢁⣴⣶⣄⠀⠀⠉⠉⠉⠀⢻⣿⡿⢰⣿⡇⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢿⣿⠟⠋⠀⠈⠛⣿⣿⠀⠀⠀⠀⠀⠀⠸⣿⡇⢸⣿⡇⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢸⣿⠀⠀⠀⠀⠀⠘⠿⠆⠀⠀⠀⠀⠀⠀⣿⡇⠀⠿⠇
</pre>
