# Using GameCube Controllers with Dolphin's Integrated mGBA on macOS

**A workaround for using GameCube controllers through Dolphin's integrated mGBA.**

I have a Gamecube controller to USB adapter from the WiiU days that I wanted to use to have 4 GC controllers control mGBA instances in Dolphin (e.g., to play Four Swords Adventure or Final Fantasy Crystal Chronicles). Unfortunately, Dolphin doesn't seem to recognize the controllers via this adapter as normal digital controller inputs, something to do with a weird Nintendo USB protocol - at least on my Mac. So I worked with ChatGPT to make this workaround. 

**A caveat:** So far I've tested the controller inputs one at a time, not a full four-player session simultaneously.

## How it works

```text
GameCube controllers
        ↓
Official Wii U USB adapter
        ↓
Python + PyUSB + libusb
        ↓
OpenJoystickDriver (OJD)
        ↓
Four virtual gamepads
        ↓
Dolphin's integrated mGBA
```

Python reads the adapter's USB reports, separates the four controller ports, and sends their inputs to four independent virtual gamepads through OpenJoystickDriver.

## Tested setup

| Component | Version / hardware |
| --- | --- |
| macOS | 26.2, Apple Silicon |
| Dolphin | 2609a |
| USB adapter | Official Nintendo Wii U GameCube Controller Adapter (WUP-028) |
| Controllers | Four wired GameCube controllers |
| GCAdapterDriver | v1.6 — installed and active throughout testing; **not confirmed to be required, I just had it on the whole time** |
| OpenJoystickDriver | 0.6.0-alpha.1 |
| Python | Python 3, PyUSB, libusb 1.0.30 |

## Prerequisites

- [Dolphin Emulator](https://dolphin-emu.org/)
- [OpenJoystickDriver]([https://github.com/OpenJoystickDriver](https://github.com/xsyetopz/OpenJoystickDriver)) (OJD), with its service and virtual gamepad functionality enabled
- [GCAdapterDriver](https://github.com/secretkeysio/GCAdapterDriver) — used in my tested setup, although I haven't verified whether it's strictly necessary for this Python-based approach
- Python 3
- The official Wii U GameCube controller adapter

Install and configure the relevant software, then restart your Mac if the driver installers ask you to.

### 1. Verify the adapter and OpenJoystickDriver

If you're using GCAdapterDriver, make sure it's active. On my Mac, it's a toggle in the menu bar near the clock, Wi-Fi, and battery icons.

In Terminal, run:

```bash
ojd diagnose
```

Look for a running service, active transport extension, and enabled virtual-device functionality.

**It's okay if OJD reports zero physical USB controllers.** Python will access the GameCube adapter directly; OJD will provide the virtual gamepads.

You can also confirm that macOS detects the adapter under **System Information → USB**, where it should appear as **WUP-028**.

<!-- Optional: add a screenshot at images/wup-028-system-information.png -->

### 2. Set up Python, PyUSB, and libusb

Create a Python virtual environment and install PyUSB:

```bash
python3 -m venv ~/gcadapter-venv
source ~/gcadapter-venv/bin/activate
python -m pip install pyusb
```

PyUSB also requires the native **libusb** library.

On my Apple Silicon Mac running macOS 26.2, I used a precompiled MacPorts libusb 1.0.30 package **without installing MacPorts itself**:

```bash
mkdir -p ~/libusb-local
cd ~/libusb-local

curl -LO https://packages.macports.org/libusb/libusb-1.0.30_0.darwin_25.arm64.tbz2

tar -xjf libusb-1.0.30_0.darwin_25.arm64.tbz2
```

> **Compatibility note:** This binary is for **Apple Silicon / Darwin 25**. Other macOS versions or Intel Macs may require a different libusb build. The important thing is that PyUSB can load a compatible libusb library.

Check that the backend loads:

```bash
DYLD_LIBRARY_PATH="$HOME/libusb-local/opt/local/lib" \
python -c "import usb.backend.libusb1 as b; print(b.get_backend())"
```

You should see a libusb backend object rather than `None`.

### 3. Get the Python bridge

Download [`gcadapter_bridge.py`](./gcadapter_bridge.py) from this repository and save it in your home directory:

```text
~/gcadapter_bridge.py
```

The script:

- Detects the official Wii U adapter (USB ID `057e:0337`).
- Claims its USB interface.
- Reads the four GameCube controller ports.
- Translates buttons, analog sticks, D-pad, and triggers into virtual gamepad inputs.
- Starts four OJD virtual gamepad feeds using the `generic` profile.
- Releases the interface and stops the feeds during a normal Ctrl+C shutdown.

### 4. Run the bridge

**Close Dolphin before starting the bridge.** Leave GCAdapterDriver active if you're using it.

In Terminal:

```bash
source ~/gcadapter-venv/bin/activate

DYLD_LIBRARY_PATH="$HOME/libusb-local/opt/local/lib" \
python ~/gcadapter_bridge.py
```

Successful startup should look something like:

```text
Adapter interface claimed.
Adapter initialized.
Started four OJD virtual gamepads (generic profile).
```

**Leave this Terminal window running while you play.** You don't need `sudo`.

### 5. Configure Dolphin's integrated mGBA

With the bridge running:

1. Open Dolphin.
2. Go to the integrated mGBA input configuration.
3. Open the input-device dropdown.
4. You should now see OJD virtual gamepads, rather than only `Quartz/0/Keyboard & Mouse` or your previous device options.
5. Select a different virtual gamepad for each mGBA player and map the buttons.

That's it! The GameCube controllers should now be available as independent inputs for Dolphin's integrated mGBA instances.

**Important:** While the bridge is running, Python owns the physical adapter's USB interface. Don't also configure Dolphin to use that same adapter through its native **GameCube Controller Adapter** input mode.

### 6. Optional: change input latency

The included bridge script initially sends controller states at 180 Hz. I only tried 60, 120, and 180; felt improvement 60->120, not sure if 120 ->180 helped or not. 

To play with this, in `gcadapter_bridge.py`, change:

```python
FRAME_RATE = 180.0
```

### 7. Switch back to normal Dolphin controls

When you're finished using the controllers with mGBA:

1. Press **Ctrl+C** in the Terminal running the bridge or exit the program.
2. The script shuts down the virtual gamepads and releases the USB interface.
3. Dolphin can then use the GameCube adapter normally for other games.

You shouldn't need to uninstall drivers or change any permanent settings. For a clean handoff, close and reopen Dolphin after stopping the bridge if necessary.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| **Python can't find libusb** | Launch Python with the `DYLD_LIBRARY_PATH` prefix shown above and confirm the library matches your Mac's architecture. |
| **USB access denied** | Fully quit Dolphin before starting the bridge. Dolphin and Python can't claim the adapter interface simultaneously. |
| **`ojd controller list` is empty** | This command didn't list our virtual feeds even when Dolphin could see them. Check Dolphin's input-device dropdown instead. |
| **Only the keyboard appears in mGBA** | Check that the bridge is still running and that OJD's service and virtual-device functionality are active. |
| **Different USB adapter** | This script targets the **official Nintendo Wii U adapter**. Third-party adapters may use different USB protocols. |
| **Problems on other Macs** | The tested configuration is Apple Silicon on macOS 26.2. Other systems may need a different libusb installation or other adjustments. |

## Limitations / things still to verify

- Four virtual gamepads appeared in Dolphin, but I haven't yet completed a full four-player gameplay test.
- GCAdapterDriver was installed and active throughout testing; I haven't tested whether the bridge works without it.
- This is a personal workaround, not a broadly tested installer or an official Dolphin feature.

If you find ways to simplify or improve it, feel free to share them!
