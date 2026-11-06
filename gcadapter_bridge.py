#!/usr/bin/env python3
"""
Wii U GameCube Adapter -> four OpenJoystickDriver virtual gamepads.

Run with Dolphin closed:
  source ~/gcadapter-venv/bin/activate
  DYLD_LIBRARY_PATH="$HOME/libusb-local/opt/local/lib" python ~/gcadapter_bridge.py

Stop with Ctrl-C. The adapter interface is released and all four OJD feeds exit.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time

import usb.core
import usb.util

VID = 0x057E
PID = 0x0337
ENDPOINT_IN = 0x81
ENDPOINT_OUT = 0x02
REPORT_LENGTH = 37
PORT_COUNT = 4
PROFILE = "generic"
FRAME_RATE = 180.0
USB_TIMEOUT_MS = 12
DEADZONE = 0.04

# Wii U adapter button byte 1 (channel_data[1]).
B1_A = 1 << 0
B1_B = 1 << 1
B1_X = 1 << 2
B1_Y = 1 << 3
B1_LEFT = 1 << 4
B1_RIGHT = 1 << 5
B1_DOWN = 1 << 6
B1_UP = 1 << 7

# Wii U adapter button byte 2 (channel_data[2]).
B2_START = 1 << 0
B2_Z = 1 << 1
B2_R = 1 << 2
B2_L = 1 << 3


def stick_axis(raw):
    """Convert an unsigned 8-bit stick value to OJD's -1..1 range."""
    value = (float(raw) - 127.5) / 127.5
    magnitude = abs(value)
    if magnitude <= DEADZONE:
        return 0.0
    # Rescale after the deadzone so the full range remains reachable.
    return (1.0 if value > 0 else -1.0) * (
        (magnitude - DEADZONE) / (1.0 - DEADZONE)
    )


def trigger_axis(raw):
    return max(0.0, min(1.0, float(raw) / 255.0))


def neutral_frame():
    return {"buttons": [], "dpad": [], "axes": {
        "LeftStickX": 0.0,
        "LeftStickY": 0.0,
        "RightStickX": 0.0,
        "RightStickY": 0.0,
        "LeftTrigger": 0.0,
        "RightTrigger": 0.0,
    }}


def decode_port(port_data):
    # Each port record is: status, buttons1, buttons2, stickX, stickY,
    # cStickX, cStickY, analogL, analogR.
    status, b1, b2, sx, sy, cx, cy, left, right = port_data

    # Bit 4 = wired controller; bit 5 = wireless controller.
    connected = bool(status & 0x30)
    if not connected:
        return neutral_frame()

    buttons = []
    dpad = []

    if b1 & B1_A:
        buttons.append("South")
    if b1 & B1_B:
        buttons.append("East")
    if b1 & B1_X:
        buttons.append("West")
    if b1 & B1_Y:
        buttons.append("North")

    if b1 & B1_UP:
        dpad.append("DpadUp")
    if b1 & B1_DOWN:
        dpad.append("DpadDown")
    if b1 & B1_LEFT:
        dpad.append("DpadLeft")
    if b1 & B1_RIGHT:
        dpad.append("DpadRight")

    if b2 & B2_START:
        buttons.append("Start")
    if b2 & B2_Z:
        buttons.append("RightShoulder")
    if b2 & B2_L:
        buttons.append("LeftShoulder")

    return {
        "buttons": buttons,
        "dpad": dpad,
        "axes": {
            "LeftStickX": stick_axis(sx),
            "LeftStickY": stick_axis(sy),
            "RightStickX": stick_axis(cx),
            "RightStickY": stick_axis(cy),
            "LeftTrigger": trigger_axis(left),
            "RightTrigger": trigger_axis(right),
        },
    }


def start_feeds(ojd_path, feeds):
    for port in range(PORT_COUNT):
        proc = subprocess.Popen(
            [ojd_path, "virtual", "feed", "--as", PROFILE],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=None,
            text=True,
            bufsize=1,
        )
        feeds.append(proc)
        # Give OJD a moment to publish the device before starting the next.
        time.sleep(0.15)
        if proc.poll() is not None:
            raise RuntimeError(
                f"OJD feed for adapter port {port + 1} exited immediately "
                f"(exit code {proc.returncode})."
            )


def stop_feeds(feeds):
    # Send a neutral state before EOF, then allow OJD to remove each device.
    for proc in feeds:
        if proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write(json.dumps(neutral_frame()) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    for proc in feeds:
        if proc.stdin:
            try:
                proc.stdin.close()
            except OSError:
                pass

    for proc in feeds:
        if proc.poll() is None:
            try:
                proc.wait(timeout=2.5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def main():
    ojd_path = shutil.which("ojd")
    if not ojd_path:
        print("ERROR: 'ojd' was not found in PATH.", file=sys.stderr)
        print("Run this from the terminal where the OJD command works.", file=sys.stderr)
        return 1

    print("Looking for Nintendo Wii U GameCube Adapter (057e:0337)...")
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("ERROR: Adapter not found. Check its USB connection.", file=sys.stderr)
        return 1

    claimed = False
    feeds = []
    return_code = 0
    try:
        # The adapter is already configured in the successful diagnostic test.
        usb.util.claim_interface(dev, 0)
        claimed = True
        print("Adapter interface claimed.")

        # Start the adapter's continuous input reports.
        dev.write(ENDPOINT_OUT, [0x13], timeout=1000)
        print("Adapter initialized.")

        start_feeds(ojd_path, feeds)
        print("Started four OJD virtual gamepads (generic profile).")
        print("Move/press each controller to test it in mGBA.")
        print("Press Ctrl-C here to stop and return the adapter to Dolphin.")

        latest = [neutral_frame() for _ in range(PORT_COUNT)]
        period = 1.0 / FRAME_RATE
        next_publish = time.monotonic()

        while True:
            # Read the adapter as quickly as it reports, retaining the latest
            # state. OJD frames are deliberately published at 60 Hz because
            # each feed frame is held for at least 8 ms.
            try:
                report = bytes(dev.read(
                    ENDPOINT_IN, REPORT_LENGTH, timeout=USB_TIMEOUT_MS
                ))
                if len(report) == REPORT_LENGTH and report[0] == 0x21:
                    for port in range(PORT_COUNT):
                        start = 1 + (9 * port)
                        latest[port] = decode_port(report[start:start + 9])
            except usb.core.USBTimeoutError:
                pass

            now = time.monotonic()
            if now >= next_publish:
                for index, proc in enumerate(feeds):
                    if proc.poll() is not None:
                        raise RuntimeError(
                            f"OJD feed for port {index + 1} exited "
                            f"(exit code {proc.returncode})."
                        )
                    proc.stdin.write(json.dumps(latest[index], separators=(",", ":")) + "\n")
                    proc.stdin.flush()

                next_publish += period
                if next_publish < now - period:
                    next_publish = now + period

    except KeyboardInterrupt:
        print("\nStopping bridge...")
    except usb.core.USBError as exc:
        print(f"\nUSB ERROR: {exc}", file=sys.stderr)
        return_code = 1
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return_code = 1
    else:
        return_code = 0
    finally:
        if feeds:
            stop_feeds(feeds)
        if claimed:
            try:
                usb.util.release_interface(dev, 0)
                print("Adapter interface released.")
            except usb.core.USBError as exc:
                print(f"Warning: could not release interface cleanly: {exc}", file=sys.stderr)
        usb.util.dispose_resources(dev)

    print("Bridge stopped. You can now open Dolphin and use the adapter normally.")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
