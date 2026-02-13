# core/perception/ocr/ocr_remote.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import requests
from core.perception.ocr.interface import OCRInterface
from core.utils.logger import logger_uma
from PIL import Image


def _prepare_bgr3(img: Any) -> np.ndarray:
    """
    Convert any image format to 3-channel BGR numpy array for encoding.
    """
    if isinstance(img, Image.Image):
        bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    elif isinstance(img, np.ndarray):
        bgr = img
    else:
        from core.utils.img import to_bgr
        bgr = to_bgr(img)
    
    # Normalize to 3-channel BGR
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    
    return bgr


class RemoteOCREngine(OCRInterface):
    """
    HTTP client that calls a backend OCR service (FastAPI) at <base_url>/ocr.
    Keeps the same method signatures as the local engine.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _post(self, data: Dict[str, Any] = None, files: Dict = None) -> Dict[str, Any]:
        """
        Send OCR request using multipart/form-data (optimized) or JSON (legacy fallback).
        """
        url = f"{self.base_url}/ocr"
        # start_time = time.perf_counter()
        
        if files:
            # Multipart upload (optimized)
            r = self.session.post(url, data=data, files=files, timeout=self.timeout)
        else:
            # Legacy JSON behavior (should not be used anymore)
            r = self.session.post(url, json=data, timeout=self.timeout)
        
        try:
            r.raise_for_status()
        except Exception:
            logger_uma.exception(
                "RemoteOCR request failed: %s %s", r.status_code, r.text[:2000]
            )
            raise
        # finally:
            # elapsed = time.perf_counter() - start_time
            # logger_uma.debug("RemoteOCR request took %.3fs", elapsed)
        
        response_data = r.json()
        if "data" not in response_data:
            raise ValueError(f"Unexpected response shape: {response_data}")
        return response_data

    # ---- Methods ----
    def raw(self, img: Any) -> Dict[str, Any]:
        bgr = _prepare_bgr3(img)
        success, encoded_img = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not success:
            raise ValueError("Failed to encode image")
        img_bytes = encoded_img.tobytes()
        
        metadata = {"mode": "raw"}
        result = self._post(data=metadata, files={"file": ("image.jpg", img_bytes, "image/jpeg")})
        return result["data"]

    def text(self, img: Any, joiner: str = " ", min_conf: float = 0.2) -> str:
        bgr = _prepare_bgr3(img)
        success, encoded_img = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not success:
            raise ValueError("Failed to encode image")
        img_bytes = encoded_img.tobytes()
        
        metadata = {
            "mode": "text",
            "joiner": joiner,
            "min_conf": str(min_conf),
        }
        result = self._post(data=metadata, files={"file": ("image.jpg", img_bytes, "image/jpeg")})
        return result["data"]

    def digits(self, img: Any) -> int:
        bgr = _prepare_bgr3(img)
        success, encoded_img = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not success:
            raise ValueError("Failed to encode image")
        img_bytes = encoded_img.tobytes()
        
        metadata = {"mode": "digits"}
        result = self._post(data=metadata, files={"file": ("image.jpg", img_bytes, "image/jpeg")})
        return int(result["data"])

    def batch_text(
        self, imgs: List[Any], *, joiner: str = " ", min_conf: float = 0.2
    ) -> List[str]:
        # For batch operations, encode multiple images
        files_list = []
        for idx, im in enumerate(imgs):
            bgr = _prepare_bgr3(im)
            success, encoded_img = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            if not success:
                raise ValueError(f"Failed to encode image {idx}")
            img_bytes = encoded_img.tobytes()
            files_list.append(("files", (f"image_{idx}.jpg", img_bytes, "image/jpeg")))
        
        metadata = {
            "mode": "batch_text",
            "joiner": joiner,
            "min_conf": str(min_conf),
        }
        result = self._post(data=metadata, files=files_list)
        return list(result["data"])

    def batch_digits(self, imgs: List[Any]) -> List[str]:
        # For batch operations, encode multiple images
        files_list = []
        for idx, im in enumerate(imgs):
            bgr = _prepare_bgr3(im)
            success, encoded_img = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            if not success:
                raise ValueError(f"Failed to encode image {idx}")
            img_bytes = encoded_img.tobytes()
            files_list.append(("files", (f"image_{idx}.jpg", img_bytes, "image/jpeg")))
        
        metadata = {"mode": "batch_digits"}
        result = self._post(data=metadata, files=files_list)
        return list(result["data"])
