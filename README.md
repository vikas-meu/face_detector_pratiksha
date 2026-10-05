# Face Detector with Master Face (OpenCV + Python)

A face detector that **remembers your face**.

1. When the webcam starts, you get **5 seconds to register your face**.
2. That face is saved as the **master face** (`master/master_face.jpg`).
3. From then on:
   - your face gets a **green box** labelled **`MASTER`**
   - every other face gets a **red box** labelled **`NOT MASTER`**

It also works on **photos** and **video files**, and it runs on Windows, macOS and Linux.
The only package it needs is `opencv-python`. Setup downloads the two small official OpenCV face models for you.

---

## What you need

- A Windows, macOS, or Linux computer
- **Python 3.8 or newer**
- A webcam
- An internet connection for the one-time setup (about 40 MB)

---

## Step 1: Install Python

### Windows
1. Go to <https://www.python.org/downloads/> and click **Download Python 3.x**.
2. Run the installer.
3. **Important:** on the first screen, tick **"Add python.exe to PATH"**, then click **Install Now**.
4. To check it worked, open **Command Prompt** (press `Win`, type `cmd`, press Enter) and run:
   ```
   python --version
   ```
   You should see something like `Python 3.12.x`.

### macOS
1. Download the macOS installer from <https://www.python.org/downloads/> and run it.
2. Open **Terminal** and check:
   ```
   python3 --version
   ```

### Linux (Ubuntu/Debian)
```
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

---

## Step 2: Download this project

**Option A: download a ZIP (easiest)**
1. Open <https://github.com/vikas-meu/face_detector_pratiksha>.
2. Click the green **Code** button, then **Download ZIP**.
3. Right-click the ZIP and choose **Extract All** (Windows), or double-click it (macOS).
4. Open the extracted folder `face_detector_pratiksha-main`.

**Option B: with Git**
```
git clone https://github.com/vikas-meu/face_detector_pratiksha.git
cd face_detector_pratiksha
```

The folder should contain:

```
face_detector_pratiksha/
├── face_detector.py       <- the program
├── requirements.txt       <- list of packages to install
├── setup_windows.bat      <- one-click setup (Windows)
├── run_windows.bat        <- one-click start (Windows)
├── setup_mac_linux.sh     <- setup script (macOS/Linux)
└── README.md              <- this guide
```

---

## Step 3: Set it up (one time only)

### Windows: the easy way
1. Open the project folder.
2. Double-click **`setup_windows.bat`**.
3. Wait until it says **"Setup complete!"** (about 1–3 minutes).

> If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.

### Windows: the manual way
Open Command Prompt in the project folder (in File Explorer, click the address bar,
type `cmd`, and press Enter), then run:
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python face_detector.py --download-models
```

### macOS / Linux
Open Terminal in the project folder and run:
```
bash setup_mac_linux.sh
```
Or do it by hand:
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python face_detector.py --download-models
```

> **What is `venv`?** It's a private folder where this project's packages are installed,
> so they don't interfere with anything else on your computer. To uninstall later,
> just delete the project folder.

---

## Step 4: Register your master face and run it

Start the program:
- **Windows:** double-click **`run_windows.bat`**
- **macOS / Linux:** `source venv/bin/activate` then `python face_detector.py`

The first time it runs:

1. A camera window opens with a yellow banner: **`REGISTERING MASTER FACE 5.0s`**.
2. **Sit alone in front of the camera**, look straight at it, and hold still.
   You can turn your head a little so it learns a few angles.
3. After 5 seconds you'll see **"Master face registered!"**, and your face appears
   in the top-right corner labelled MASTER.
4. Now ask someone else to step in. Their face gets a **red NOT MASTER** box,
   and yours stays **green MASTER**.

Your master face is saved, so next time the program goes straight to recognition.
Press **`r`** at any time to register a new master face.

### Keys

| Key | Action |
|-----|--------|
| `q` or `Esc` | Quit |
| `s` | Save a snapshot to the `output` folder |
| `r` | Register a new master face (5 seconds) |

The number next to each label (for example `MASTER 0.72`) shows how similar that face is
to the master face. 1.0 means identical, and anything above **0.36** counts as the master.

---

## Other ways to use it

```
python face_detector.py --image photo.jpg    # check faces in a photo (result saved in "output")
python face_detector.py --video clip.mp4     # check faces in a video file
python face_detector.py --register           # start with a fresh master registration
python face_detector.py --camera 1           # use a second / external webcam
python face_detector.py --threshold 0.45     # stricter matching (fewer false "MASTER")
python face_detector.py --help               # list all options
```

On Windows you can pass the same options to the launcher, for example
`run_windows.bat --image C:\Users\You\Pictures\group.jpg`.

Photo and video mode use the master face you registered with the webcam.

---

## Every time you come back

You only run setup once. After that:

- **Windows:** double-click `run_windows.bat`, **or** open Command Prompt in the folder and run:
  ```
  venv\Scripts\activate
  python face_detector.py
  ```
- **macOS / Linux:**
  ```
  source venv/bin/activate
  python face_detector.py
  ```

When the venv is active you'll see `(venv)` at the start of the command line.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `'python' is not recognized...` | Python isn't on your PATH. Reinstall Python and tick **"Add python.exe to PATH"**. You can also try `py` instead of `python`. |
| `No module named 'cv2'` | The venv isn't active or setup didn't finish. Run `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (macOS/Linux), then `pip install -r requirements.txt`. |
| `Download failed` | Check your internet connection and run setup again. Or download the two `.onnx` files from the links printed in the error and put them in a folder called `models` inside the project. |
| `Could not open webcam #0` | Close other apps using the camera (Zoom, Teams, browser tabs). Try `--camera 1`. On Windows, check **Settings > Privacy & security > Camera** and allow desktop apps. On macOS, allow Terminal under **System Settings > Privacy & Security > Camera**. |
| "Face not clear - trying again" | Registration needs your face clearly visible for most of the 5 seconds. Use good lighting, face the camera, and make sure you're the only person in view. |
| My own face shows NOT MASTER | Press `r` and register again in better light, or lower the threshold: `--threshold 0.30`. |
| Someone else shows as MASTER | Raise the threshold: `--threshold 0.45`. |
| Linux: window doesn't open / Qt error | Run `sudo apt install libgl1 libglib2.0-0`. |

---

## Privacy

Your master face is stored only on your computer, in the `master` folder
(`master_face.jpg` and `master_features.npy`). It is excluded from Git, so it is never
uploaded. Delete that folder to forget the master face.

---

## How it works

1. **YuNet** (an OpenCV face detection model) finds every face in each frame.
2. **SFace** (an OpenCV face recognition model) turns each face into a list of 128 numbers,
   a kind of "face fingerprint".
3. During the 5-second registration, fingerprints from many frames are averaged into the
   master fingerprint.
4. Every face in the frame is compared with the master fingerprint (cosine similarity).
   If the similarity is above the threshold, the face is the **MASTER**. Otherwise it is
   **NOT MASTER**.
