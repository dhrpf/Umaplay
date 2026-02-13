# core/perception/yolo/yolo_remote.py
from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
from PIL import Image
import requests

from core.perception.yolo.interface import IDetector
from core.controllers.base import IController, RegionXYWH
from core.controllers.steam import SteamController
from core.settings import Settings
from core.types import DetectionDict
from core.utils.img import pil_to_bgr, to_bgr
from core.utils.logger import logger_uma
import time

# Global counter for button collection (button_type_state -> count)
# Key format: "button_white_on", "button_white_off", etc.
_button_collection_counts: Dict[str, int] = {}

# Button classes to collect
_button_classes = ["button_white", "button_green", "button_golden", "button_pink"]


def _get_button_count(button_type: str, state: str) -> int:
    """Get current button collection count for a button type and state."""
    global _button_collection_counts
    key = f"{button_type}_{state}"
    return _button_collection_counts.get(key, 0)


def _increment_button_count(button_type: str, state: str) -> int:
    """Increment and return button collection count for a button type and state."""
    global _button_collection_counts
    key = f"{button_type}_{state}"
    _button_collection_counts[key] = _button_collection_counts.get(key, 0) + 1
    return _button_collection_counts[key]


def _collect_button_data(
    pil_img: Image.Image,
    dets: List[DetectionDict],
    classifier: Optional["ActiveButtonClassifier"] = None,
) -> None:
    """
    Automatically collect button training data based on button classifier prediction.
    
    For each button detection:
    - Crop button region
    - Run through button classifier
    - If classifier_conf >= threshold: save to datasets/button_states/{button_type}/on/
    - If classifier_conf < threshold: save to datasets/button_states/{button_type}/off/
    
    Filters out buttons with width < 125 pixels to avoid collecting small/partial detections.
    Limits collection based on Settings.BUTTON_COLLECTION_LIMIT per button type.
    Can be disabled by setting Settings.COLLECT_BUTTON_DATA = False.
    """
    import os
    import time
    from core.utils.geometry import crop_pil
    
    # Check if button collection is enabled
    if not Settings.COLLECT_BUTTON_DATA:
        return
    
    if not dets:
        return
    
    # Load classifier if not provided
    if classifier is None:
        try:
            from core.perception.is_button_active import ActiveButtonClassifier
            classifier = ActiveButtonClassifier.load("models/active_button_clf.joblib")
        except Exception as e:
            logger_uma.debug(f"[BUTTON COLLECT] Classifier not available, skipping collection: {e}")
            return
    
    try:
        base_dir = "datasets/button_states"
        ts = time.strftime("%Y%m%d-%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"
        
        for det in dets:
            button_name = det.get("name", "")
            
            # Only collect specified button classes
            if button_name not in _button_classes:
                continue
            
            yolo_conf = float(det.get("conf", 0.0))
            xyxy = det.get("xyxy")
            
            if not xyxy:
                continue
            
            # Calculate button width and skip if too small
            x1, y1, x2, y2 = xyxy
            button_width = x2 - x1
            if button_width < 125:
                continue
            
            # Crop button region from image
            button_img = crop_pil(pil_img, (int(x1), int(y1), int(x2), int(y2)))
            
            # Run through classifier to get actual button state confidence
            try:
                start_time = time.perf_counter()
                classifier_conf = classifier.predict_proba(button_img)
                end_time = time.perf_counter()
                print(f"classifier took : {end_time - start_time}")
            except Exception as e:
                logger_uma.debug(f"[BUTTON COLLECT] Classifier prediction failed: {e}")
                continue
            
            # Determine on/off based on classifier confidence threshold
            state = "on" if classifier_conf >= Settings.BUTTON_COLLECTION_THRESHOLD else "off"
            
            # Check if we've collected enough for this button type and state
            current_count = _get_button_count(button_name, state)
            if current_count >= Settings.BUTTON_COLLECTION_LIMIT:
                continue
            
            # Create output directory
            out_dir = os.path.join(base_dir, button_name, state)
            os.makedirs(out_dir, exist_ok=True)
            
            # Save with timestamp and classifier confidence
            filename = f"{button_name}_{state}_{ts}_{classifier_conf:.2f}.png"
            filepath = os.path.join(out_dir, filename)
            
            # Save image
            button_img.save(filepath)
            
            # Increment counter
            new_count = _increment_button_count(button_name, state)
            
            logger_uma.debug(
                f"[BUTTON COLLECT] {button_name} {state.upper()} ({new_count}/{Settings.BUTTON_COLLECTION_LIMIT}) "
                f"clf_conf={classifier_conf:.2f} yolo_conf={yolo_conf:.2f} w={button_width:.0f}px -> {filename}"
            )
            
    except Exception as e:
        logger_uma.debug(f"failed collecting button data: {e}")


def _encode_image_to_base64(img: Any, *, fmt: str = ".png") -> str:
    """
    Encode to base64 as a true 3-channel BGR PNG.
    - If PIL.Image: convert RGB->BGR.
    - If ndarray: assume it's already BGR (do NOT swap again).
    - Normalize grayscale/BGRA to BGR.
    """
    if isinstance(img, Image.Image):
        bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    elif isinstance(img, np.ndarray):
        bgr = img
    else:
        # last-resort fallback (path/bytes); OK to keep if you truly need it
        bgr = to_bgr(img)

    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)

    ok, buf = cv2.imencode(fmt, bgr)
    if not ok:
        raise ValueError("Failed to encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


class RemoteYOLOEngine(IDetector):
    """
    Lightweight client that calls a FastAPI /yolo service.
    No Ultralytics or CUDA required on the VM.
    """

    def __init__(
        self,
        ctrl: IController,
        base_url: str,
        *,
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
        weights: str | None = None,
    ):
        self.ctrl = ctrl
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        # Ensure JSON-serializable type (avoid WindowsPath issues)
        self.weights = str(weights) if weights is not None else None

    def _post(self, data: Dict[str, Any] = None, files: Dict = None, json_payload: Dict = None) -> Dict[str, Any]:
        """
        Refactored to support both JSON (legacy) and Multipart (optimized)
        """
        url = f"{self.base_url}/yolo"
        
        if files:
            # Multipart upload
            r = self.session.post(url, data=data, files=files, timeout=self.timeout)
        else:
            # Legacy JSON behavior
            r = self.session.post(url, json=json_payload, timeout=self.timeout)

        r.raise_for_status()
        return r.json()

    # ---------- public API ----------
    def detect_bgr(
        self,
        bgr: np.ndarray,
        *,
        imgsz: Optional[int] = None,
        conf: Optional[float] = None,
        iou: Optional[float] = None,
        tag: str = "general",
        agent: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], List[DetectionDict]]:
        imgsz = imgsz if imgsz is not None else Settings.YOLO_IMGSZ
        conf = conf if conf is not None else Settings.YOLO_CONF
        iou = iou if iou is not None else Settings.YOLO_IOU

        success, encoded_img = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        img_bytes = encoded_img.tobytes()

        # 4. Prepare Metadata (Must be strings for multipart/form-data)
        metadata = {
            "imgsz": str(imgsz),
            "conf": str(conf),
            "iou": str(iou),
            "weights_path": self.weights,
            "tag": tag,
            "agent": agent or "",
        }

        # start_time = time.perf_counter()
        
        # 5. Send as Multipart
        data = self._post(data=metadata, files={"file": ("image.jpg", img_bytes, "image/jpeg")})
        
        # end_time = time.perf_counter()
        
        # logger_uma.debug(
        #     "remote yolo (optimized): (%.3f s)",
        #     end_time - start_time,
        # )
        meta = data.get(
            "meta", {"backend": "remote", "imgsz": imgsz, "conf": conf, "iou": iou}
        )
        dets: List[DetectionDict] = data.get("dets", [])
        if tag:
            meta.setdefault("tag", tag)
        if agent:
            meta.setdefault("agent", agent)
        return meta, dets

    def detect_pil(
        self,
        pil_img: Image.Image,
        *,
        imgsz: Optional[int] = None,
        conf: Optional[float] = None,
        iou: Optional[float] = None,
        tag: str = "general",
        agent: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], List[DetectionDict]]:
        bgr = pil_to_bgr(pil_img)
        meta, dets = self.detect_bgr(
            bgr,
            imgsz=imgsz,
            conf=conf,
            iou=iou,
            tag=tag,
            agent=agent,
        )
        
        # Collect button training data on client side
        # _collect_button_data(pil_img, dets)
        
        return meta, dets

    @staticmethod
    def _maybe_store_debug(
        pil_img: Image.Image,
        dets: List[DetectionDict],
        *,
        tag: str,
        thr: float,
        agent: Optional[str] = None,
    ) -> None:
        import os, time

        if not Settings.STORE_FOR_TRAINING or not dets:
            return
        lows = [d for d in dets if float(d.get("conf", 0.0)) <= float(thr)]
        if not lows:
            return
        try:
            agent_segment = (agent or "").strip()
            base_dir = Settings.DEBUG_DIR / agent_segment if agent_segment else Settings.DEBUG_DIR
            out_dir_raw = base_dir / tag / "raw"
            os.makedirs(out_dir_raw, exist_ok=True)

            ts = (
                time.strftime("%Y%m%d-%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"
            )

            lowest = min(lows, key=lambda d: float(d.get("conf", 0.0)))
            conf_line = f"{float(lowest.get('conf', 0.0)):.2f}"
            raw_name = str(lowest.get("name", "unknown")).strip()
            class_segment = "".join(
                ch if ch.isalnum() or ch in "-_" else "-" for ch in raw_name
            ) or "unknown"

            raw_path = out_dir_raw / f"{tag}_{ts}_{class_segment}_{conf_line}.png"
            pil_img.save(raw_path)
            logger_uma.debug("saved low-conf training debug -> %s", raw_path)
        except Exception as e:
            logger_uma.debug("failed saving training debug: %s", e)

    def recognize(
        self,
        *,
        region: Optional[RegionXYWH] = None,
        imgsz: Optional[int] = None,
        conf: Optional[float] = None,
        iou: Optional[float] = None,
        tag: str = "general",
        agent: Optional[str] = None,
    ):
        if self.ctrl is None:
            raise RuntimeError(
                "RemoteYOLOEngine.recognize() requires a controller injected in the constructor."
            )

        if isinstance(self.ctrl, SteamController):
            img = self.ctrl.screenshot_left_half()
        else:
            img = self.ctrl.screenshot(region=region)

        meta, dets = self.detect_pil(
            img,
            imgsz=imgsz,
            conf=conf,
            iou=iou,
            tag=tag,
            agent=agent,
        )

        if not Settings.USE_EXTERNAL_PROCESSOR:
            # otherwise it is already saved in external processor
            self._maybe_store_debug(
                img,
                dets,
                tag=tag,
                thr=Settings.STORE_FOR_TRAINING_THRESHOLD,
                agent=agent,
            )

        return img, meta, dets
