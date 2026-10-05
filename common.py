"""Helpers shared by all the apps in this project."""

import os
import sys
import time
import urllib.request

import cv2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def download_model(filename, url, min_size=100_000):
    """Download a model file into the "models" folder once and return its path."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    path = os.path.join(MODELS_DIR, filename)
    if os.path.exists(path):
        return path

    print(f"Downloading {filename} (one time only)...")
    tmp_path = path + ".part"
    try:
        urllib.request.urlretrieve(url, tmp_path)
    except Exception as exc:
        print(f"Download failed: {exc}")
        print(f"Download it manually from:\n  {url}\nand put it in the folder:\n  {MODELS_DIR}")
        sys.exit(1)
    if os.path.getsize(tmp_path) < min_size:
        os.remove(tmp_path)
        print(f"The download of {filename} looks broken. Please try again,")
        print(f"or download it manually from:\n  {url}")
        sys.exit(1)
    os.replace(tmp_path, path)
    return path


def open_camera(index=0, width=None, height=None):
    """Open a webcam. Exits with a helpful message if it can't be opened."""
    cap = None
    # On Windows the DirectShow backend opens webcams much faster
    if sys.platform.startswith("win"):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = None
    if cap is None:
        cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        print(f"Could not open webcam #{index}. Is it connected and not used by another app?")
        print("Try a different camera with:  --camera 1")
        sys.exit(1)
    if width and height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def save_image(image, prefix):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.jpg")
    cv2.imwrite(path, image)
    print(f"Saved {path}")
    return path


def window_closed(window):
    """True if the user closed the window with the X button."""
    return cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1


class FrameClock:
    """Gives strictly increasing millisecond timestamps (MediaPipe video mode needs them)."""

    def __init__(self):
        self.last = -1

    def next(self):
        self.last = max(int(time.monotonic() * 1000), self.last + 1)
        return self.last
