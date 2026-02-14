from __future__ import annotations

import io
import random
import re
import subprocess
import time
import threading
import cv2
import numpy as np
import scrcpy

from typing import Optional, Tuple, Union
from threading import Lock
from PIL import Image

from core.controllers.base import IController, RegionXYWH
from core.types import XYXY
from adbutils import adb  # pip install adbutils

class ScrcpyADBController(IController):
    """
    Controller that interacts with Android devices via ADB commands.
    Now equipped with Scrcpy for zero-latency screenshots.
    """

    def __init__(
        self,
        device: Optional[str] = None,
        *,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
        auto_connect: bool = True,
    ) -> None:
        super().__init__(window_title="", capture_client_only=False)
        self.device = (device or "").strip() or None
        self._screen_width = screen_width
        self._screen_height = screen_height
        # --- SCRCPY SETUP ---
        self._watchdog_active = True
        self._frame_lock = Lock()
        self._last_frame = None
        self._scrcpy_active = False
        self._last_frame_time = time.time()
        self._client_lock = Lock()
        self._running = True
        self._death_counter = 0
        adb.connect(self.device, timeout=3.0)
        self.android_device = adb.device(serial=self.device)

        if auto_connect and self.device:
            self._auto_connect_device(self.device)
            self._detect_screen_size()

        if self._screen_width is None or self._screen_height is None:
            self._detect_screen_size()

        try:
            self._init_scrcpy()
            # self._start_debug_window()
        except Exception as e:
            print(f"[Warning] Scrcpy failed to start: {e}. Falling back to standard ADB capture.")

        
        # 2. Start Watchdog
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()
    
    def stop(self):
        """Explicitly stops the background threads and Scrcpy client."""
        if not self._running: 
            return # Already stopped
            
        print("[ADBController] Shutting down vision system...")
        self._running = False # This kills the watchdog loop
        
        # Stop Scrcpy Client
        with self._client_lock:
            try:
                if hasattr(self, 'client') and self.client:
                    self.client.stop()
            except Exception as e:
                print(f"Error stopping scrcpy: {e}")
            self._scrcpy_active = False
        
        adb.disconnect(self.device)

    def __del__(self):
        """Destructor: Auto-called when the object is garbage collected."""
        self.stop()

    # ------------------------------------------------------------------
    # NEW: Debug Window Logic
    # ------------------------------------------------------------------
    def _start_debug_window(self):
        """Starts a thread that updates the OpenCV window at 30 FPS."""
        def _loop():
            print("[DEBUG] Debug Window Started. Press 'q' on the window to close it.")
            while True:
                img = None
                with self._frame_lock:
                    if self._last_frame is not None:
                        # Copy it so we don't lock the main thread while drawing
                        img = self._last_frame.copy()
                
                if img is not None:
                    # Draw overlay info
                    h, w = img.shape[:2]
                    text = f"Vision: {w}x{h} | Native: {self._screen_width}x{self._screen_height}"
                    cv2.putText(img, text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 
                                0.5, (0, 255, 0), 1, cv2.LINE_AA)
                    
                    cv2.imshow("Bot View (Scrcpy)", img)
                    
                # Check for 'q' key or window close
                if cv2.waitKey(30) & 0xFF == ord('q'):
                    cv2.destroyAllWindows()
                    break
        
        t = threading.Thread(target=_loop)
        t.daemon = True
        t.start()

    def _on_frame(self, frame):
        if frame is not None:
            with self._frame_lock:
                self._last_frame = frame
                self._last_frame_time = time.time() # <--- I'm alive!
    # ------------------------------------------------------------------
    # Scrcpy Integration (New)
    # ------------------------------------------------------------------
    def _init_scrcpy(self):
        """Safe wrapper to start/restart scrcpy."""
        if not self._running: return

        with self._client_lock:
            # Cleanup old client if exists
            try:
                if hasattr(self, 'client') and self.client:
                    self.client.stop()
                    self._death_counter = 0
            except:
                pass

            try:
                # Same settings as before
                self.client = scrcpy.Client(
                    device=self.android_device.serial,
                    max_width=0,
                    bitrate=4000000,
                    max_fps=30,
                    flip=False
                )
                self.client.add_listener(scrcpy.EVENT_FRAME, self._on_frame)
                
                t = threading.Thread(target=self.client.start)
                t.daemon = True
                t.start()
                
                self._scrcpy_active = True
                # Reset timer so we don't immediately restart
                self._last_frame_time = time.time()
                print(f"[Scrcpy] Stream started for {self.device}")
                self._death_counter = 0
                
            except Exception as e:
                print(f"[Scrcpy] Start failed: {e}")
                self._scrcpy_active = False

    def _watchdog_loop(self):
        """Monitors stream health and restarts if frozen."""
        print("[Watchdog] Scrcpy monitor active.")
        while self._running:
            time.sleep(1.0) # Check every 2 seconds
            
            # If scrcpy is supposed to be active...
            if self._scrcpy_active:
                gap = time.time() - self._last_frame_time
                
                # ...but we haven't seen a frame in 5 seconds
                if gap > 1.0:
                    print(f"[Watchdog] Stream frozen (last frame {gap:.1f}s ago). Restarting...")
                    self._scrcpy_active = False # Triggers fallback to ADB instantly
                    self._init_scrcpy()
                    self._death_counter += 1

    # ------------------------------------------------------------------
    # Helpers (Original)
    # ------------------------------------------------------------------
    def _adb_command(self, *args: str, text: bool = True, timeout: float = 10.0) -> subprocess.CompletedProcess:
        cmd = ["adb"]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(args)

        try:
            start_time = time.perf_counter()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=text,
                timeout=timeout,
                check=False,
            )
            end_time = time.perf_counter()
            # print(f"ADB command {cmd} took {end_time - start_time:.2f} seconds")
        except FileNotFoundError as exc:  # pragma: no cover - adb missing
            raise RuntimeError(
                "ADB executable not found. Install Android Platform Tools and ensure 'adb' is on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"ADB command timed out: {' '.join(cmd)}") from exc

        if result.returncode != 0:
            stderr = result.stderr if text else result.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"ADB command failed ({' '.join(cmd)}): {stderr.strip()}")

        return result

    def _auto_connect_device(self, device: str) -> None:
        try:
            listing = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return

        if listing.returncode == 0 and device in listing.stdout:
            return

        try:
            subprocess.run(
                ["adb", "connect", device],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            time.sleep(0.5)
        except Exception:
            pass

    def _detect_screen_size(self) -> None:
        try:
            result = self._adb_command("shell", "wm", "size")
            for line in result.stdout.splitlines():
                if "size:" in line.lower() and "x" in line:
                    payload = line.split("size:")[-1].strip()
                    width_str, height_str = payload.split("x", 1)
                    self._screen_width = int(width_str.strip())
                    self._screen_height = int(height_str.strip())
                    return
        except Exception:
            pass

        try:
            result = self._adb_command("shell", "dumpsys", "display")
            match = re.search(r"init=(\d+)x(\d+)", result.stdout)
            if match:
                self._screen_width = int(match.group(1))
                self._screen_height = int(match.group(2))
                return
        except Exception:
            pass

        self._screen_width = self._screen_width or 1920
        self._screen_height = self._screen_height or 1080

    def _list_devices(self) -> list[str]:
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                return []
            lines = result.stdout.strip().splitlines()[1:]
            return [line.split()[0] for line in lines if "device" in line and "offline" not in line]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Abstract overrides
    # ------------------------------------------------------------------
    def _find_window(self):  # pragma: no cover - not applicable
        return None

    def _get_hwnd(self) -> Optional[int]:  # pragma: no cover - not applicable
        return None

    def _client_bbox_screen_xywh(self) -> Optional[RegionXYWH]:
        if self._screen_width and self._screen_height:
            return (0, 0, self._screen_width, self._screen_height)
        return None

    def focus(self) -> bool:
        devices = self._list_devices()
        if not devices:
            return False
        if not self.device:
            return True
        prefix = self.device.split(":", 1)[0]
        return any(dev == self.device or dev.startswith(prefix) for dev in devices)

    def scroll(
        self,
        delta_or_xyxy: Union[int, XYXY],
        *,
        steps: int = 1,
        default_down: bool = True,
        invert: bool = False,
        min_px: int = 30,
        jitter: int = 6,
        duration_range: Tuple[float, float] = (0.16, 0.26),
        pause_range: Tuple[float, float] = (0.03, 0.07),
        end_hold_range: Tuple[float, float] = (0.05, 0.12),
        max_pixels_ratio: Optional[float] = 0.35,
    ) -> bool:
        if not (self._screen_width and self._screen_height):
            return False

        width, height = self._screen_width, self._screen_height
        use_xyxy = isinstance(delta_or_xyxy, (tuple, list)) and len(delta_or_xyxy) == 4
        if use_xyxy:
            x1, y1, x2, y2 = map(float, delta_or_xyxy)  # type: ignore[arg-type]
            cx, cy = self.center_from_xyxy((x1, y1, x2, y2))
            pixels = max(min_px, int(abs(y2 - y1)))
            scroll_down = default_down
        else:
            cx, cy = width // 2, height // 2
            delta = int(delta_or_xyxy)
            scroll_down = delta < 0
            pixels = max(min_px, abs(delta))

        if invert:
            scroll_down = not scroll_down

        def _clamp_y(y: int) -> int:
            return max(10, min(height - 10, y))

        if max_pixels_ratio is not None and max_pixels_ratio > 0:
            max_pixels_allowed = max(min_px, int(height * max_pixels_ratio))
            pixels = min(pixels, max_pixels_allowed)

        for _ in range(max(1, int(steps))):
            half = pixels // 2
            if scroll_down:
                y_start = _clamp_y(cy + half)
                y_end = _clamp_y(cy - half)
            else:
                y_start = _clamp_y(cy - half)
                y_end = _clamp_y(cy + half)

            jitter_val = int(jitter)
            xj = cx + (random.randint(-jitter_val, jitter_val) if jitter_val else 0)
            y0j = y_start + (random.randint(-jitter_val, jitter_val) if jitter_val else 0)
            y1j = y_end + (random.randint(-jitter_val, jitter_val) if jitter_val else 0)

            duration_ms = int(random.uniform(*duration_range) * 1000)
            self._adb_command(
                "shell",
                "input",
                "swipe",
                str(max(0, min(width - 1, int(xj)))),
                str(max(0, min(height - 1, int(y0j)))),
                str(max(0, min(width - 1, int(xj)))),
                str(max(0, min(height - 1, int(y1j)))),
                str(max(1, duration_ms)),
            )
            time.sleep(random.uniform(*end_hold_range) * 2)

            # Hold at end position to reduce inertia
            hold_ms = int(random.uniform(*end_hold_range) * 1000)
            if hold_ms > 0:
                hold_timeout = (hold_ms / 1000.0) + 5.0  # Add 5s buffer
                self._adb_command(
                    "shell",
                    "input",
                    "swipe",
                    str(max(0, min(width - 1, int(xj)))),
                    str(max(0, min(height - 1, int(y1j)))),
                    str(max(0, min(width - 1, int(xj)))),
                    str(max(0, min(height - 1, int(y1j)))),
                    str(max(1, hold_ms)),
                    timeout=hold_timeout,
                )

            time.sleep(random.uniform(*pause_range))

        return True

    # ------------------------------------------------------------------
    # Capture (UPDATED) & Input (Original)
    # ------------------------------------------------------------------
    def screenshot(self, region: Optional[RegionXYWH] = None) -> Image.Image:
        """
        Capture screenshot. Uses Scrcpy for speed if available, otherwise ADB fallback.
        """
        img = None

        # start_time = time.perf_counter()
        # 1. Fast Path: Scrcpy
        if self._scrcpy_active:
            with self._frame_lock:
                if self._last_frame is not None:
                    # Convert BGR (OpenCV) -> RGB (PIL)
                    # We .copy() the array implicitly during conversion or explicitly to be safe
                    rgb_frame = cv2.cvtColor(self._last_frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb_frame)

        # 2. Slow Path: Fallback
        if img is None:
            # Only print this once to avoid log spam, or track state
            # print("Fallback: Scrcpy frame missing, using ADB...")
            try:
                img = self.android_device.screenshot()
            except Exception as e:
                raise RuntimeError(f"Failed to capture screenshot: {e}")

        # time.sleep(0.01)
        # end_time = time.perf_counter()
        # print(f"Screenshot took {end_time - start_time:.2f} seconds")
        # 3. Validation
        if img.mode != "RGB":
            img = img.convert("RGB")

        self._screen_width = img.width
        self._screen_height = img.height

        # 4. Region Cropping
        if region is not None:
            left, top, width, height = region
            img = img.crop((left, top, left + width, top + height))
            self._last_origin = (left, top)
            self._last_bbox = (left, top, width, height)
        else:
            self._last_origin = (0, 0)
            self._last_bbox = (0, 0, img.width, img.height)

        return img

    def move_to(self, x: int, y: int, duration: float = 0.15) -> None:  # pragma: no cover - no-op
        time.sleep(max(0.0, duration))

    def click(
        self,
        x: int,
        y: int,
        *,
        clicks: int = 1,
        duration: float = 0.15,
        use_organic_move: bool = True,
        jitter: int = 2,
    ) -> None:
        tx = int(x)
        ty = int(y)
        if jitter and jitter > 0:
            tx += random.randint(-jitter, jitter)
            ty += random.randint(-jitter, jitter)

        if self._screen_width and self._screen_height:
            tx = max(0, min(self._screen_width - 1, tx))
            ty = max(0, min(self._screen_height - 1, ty))

        if use_organic_move:
            time.sleep(random.uniform(0.12, 0.22))
            time.sleep(random.uniform(0.03, 0.08))

        for _ in range(max(1, clicks)):
            self._adb_command("shell", "input", "tap", str(tx), str(ty))
            if clicks > 1:
                time.sleep(max(0.05, duration))

    def mouse_down(
        self,
        x: int,
        y: int,
        *,
        button: str = "left",
        use_organic_move: bool = True,
        jitter: int = 2,
    ) -> None:
        self.click(x, y, clicks=1, duration=0.1, use_organic_move=use_organic_move, jitter=jitter)

    def mouse_up(self, x: int, y: int, *, button: str = "left") -> None:  # pragma: no cover - no-op
        return None

    def hold(self, x: int, y: int, seconds: float, *, jitter: int = 2) -> None:
        tx = int(x)
        ty = int(y)
        if jitter and jitter > 0:
            tx += random.randint(-jitter, jitter)
            ty += random.randint(-jitter, jitter)

        if self._screen_width and self._screen_height:
            tx = max(0, min(self._screen_width - 1, tx))
            ty = max(0, min(self._screen_height - 1, ty))

        duration_ms = int(max(0.05, seconds) * 1000)
        self._adb_command(
            "shell",
            "input",
            "swipe",
            str(tx),
            str(ty),
            str(tx),
            str(ty),
            str(max(1, duration_ms)),
        )