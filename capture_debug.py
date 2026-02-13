from __future__ import annotations

import argparse
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw

from core.controllers.steam import SteamController
from core.controllers.bluestacks import BlueStacksController
from core.controllers.android import ScrcpyController
from core.controllers.adb import ADBController
from core.perception.yolo.yolo_local import LocalYOLOEngine
from core.perception.ocr.ocr_local import LocalOCREngine
from core.settings import Settings
from core.types import DetectionDict


def _build_controller(mode: str, window_title: str | None):
    mode = (mode or "steam").strip().lower()
    if mode not in {"steam", "bluestack", "scrcpy", "adb"}:
        raise SystemExit(
            f"Unsupported mode '{mode}'. Use one of: steam | bluestack | scrcpy | adb"
        )

    title = window_title or Settings.resolve_window_title(mode)

    if mode == "steam":
        return SteamController(window_title=title, capture_client_only=True)
    if mode == "bluestack":
        return BlueStacksController(window_title=title, capture_client_only=True)
    if mode == "adb":
        device = Settings.ADB_DEVICE
        return ADBController(device="192.168.0.163:5555")
    # scrcpy
    return ScrcpyController(window_title=title, capture_client_only=True)


def _draw_overlay(img: Image.Image, dets: list[DetectionDict], ocr_results: dict[int, str] = None) -> Image.Image:
    ov = img.copy()
    draw = ImageDraw.Draw(ov)
    for i, d in enumerate(dets):
        x1, y1, x2, y2 = [int(v) for v in d.get("xyxy", (0, 0, 0, 0))]
        name = str(d.get("name", "?"))
        conf = float(d.get("conf", 0.0))

        draw.rectangle([x1, y1, x2, y2], outline=(0, 200, 255), width=2)
        label = f"{name} {conf:.2f}"
        
        # Add OCR text if available
        if ocr_results and i in ocr_results:
            ocr_text = ocr_results[i]
            if ocr_text:
                label += f" | OCR: {ocr_text}"
        
        # text background box
        try:
            tb = draw.textbbox((0, 0), label)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:
            tw, th = int(draw.textlength(label)), 12
        pad = 3
        by1 = y1 - th - 2 * pad - 2
        if by1 < 0:
            by1 = y1 + 2
        draw.rectangle(
            [x1, by1, x1 + tw + 2 * pad, by1 + th + 2 * pad], fill=(0, 200, 255)
        )
        draw.text((x1 + pad, by1 + pad), label, fill=(0, 0, 0))
    return ov


def main():
    parser = argparse.ArgumentParser(
        description="Capture a frame and run YOLO (nav) detections for debugging."
    )
    parser.add_argument(
        "--mode",
        choices=["steam", "bluestack", "scrcpy", "adb"],
        default=Settings.MODE,
        help="Capture mode / target window type",
    )
    parser.add_argument(
        "--window-title",
        dest="window_title",
        default=None,
        help="Override window title for the selected mode",
    )
    parser.add_argument(
        "--imgsz", type=int, default=Settings.YOLO_IMGSZ, help="YOLO image size"
    )
    # Conditional defaults handled in code: nav -> 0.10, training -> Settings.YOLO_CONF
    parser.add_argument(
        "--conf",
        type=float,
        default=None,
        help="Confidence threshold. Default: 0.10 for nav, Settings.YOLO_CONF for training",
    )
    parser.add_argument(
        "--iou", type=float, default=Settings.YOLO_IOU, help="IOU threshold"
    )
    # If not provided, weights auto-select by --yolo-config: nav -> Settings.YOLO_WEIGHTS_NAV, training -> Settings.YOLO_WEIGHTS_URA
    parser.add_argument(
        "--weights",
        type=str,
        default=None,
        help="Path to YOLO weights. If omitted, picks nav/training weights based on --yolo-config",
    )
    parser.add_argument(
        "--yolo-config",
        choices=["nav", "training"],
        default="training",
        help="Select model configuration: navigation model or general training model",
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Path to save overlay image. Default: ./debug_nav_overlay.png",
    )
    parser.add_argument(
        "--tag", type=str, default="capture_nav_debug", help="Tag for debug"
    )
    parser.add_argument(
        "--remote",
        type=bool,
        default=False,
        help="Use remote YOLO engine (requires --remote-url)",
    )
    parser.add_argument(
        "--remote-url",
        type=str,
        default="http://localhost:8001",
        help="URL for remote YOLO engine (requires --remote)",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Run OCR on detected boxes",
    )
    args = parser.parse_args()

    ctrl = _build_controller(args.mode, args.window_title)

    # Focus the window (best-effort)
    ctrl.focus()

    # Resolve weights & thresholds based on yolo-config if not explicitly provided
    auto_weights = (
        str(Settings.YOLO_WEIGHTS_NAV)
        if args.yolo_config == "nav"
        else str(Settings.YOLO_WEIGHTS_URA)
    )
    weights_path = args.weights or auto_weights
    conf_thr = (
        args.conf
        if args.conf is not None
        else (0.10 if args.yolo_config == "nav" else float(Settings.YOLO_CONF))
    )

    if args.remote and args.remote_url:
        from core.perception.yolo.yolo_remote import RemoteYOLOEngine

        engine = RemoteYOLOEngine(
            ctrl=ctrl, base_url=args.remote_url, weights=weights_path
        )
    else :
        engine = LocalYOLOEngine(ctrl=ctrl, weights=weights_path)

    # Recognize (engine will decide special-cases like Steam left-half)
    img, meta, dets = engine.recognize(
        imgsz=args.imgsz, conf=conf_thr, iou=args.iou, tag=args.tag
    )

    # Print a concise report
    print("=== CaptureNavDebug ===")
    print(f"Mode: {args.mode} | Window: {ctrl.window_title}")
    print(f"YOLO config: {args.yolo_config} | Weights: {weights_path}")
    print(f"imgsz={meta.get('imgsz')} conf={meta.get('conf')} iou={meta.get('iou')}")
    print(f"Detections: {len(dets)}")
    
    # Run OCR on detected boxes if requested
    ocr_results = {}
    if args.ocr and dets:
        print("\n=== Running OCR on detected boxes ===")
        if args.remote_url:
            from core.perception.ocr.ocr_remote import RemoteOCREngine
            ocr_engine = RemoteOCREngine(base_url=args.remote_url)
        else:
            ocr_engine = LocalOCREngine()
        
        for i, d in enumerate(dets):
            x1, y1, x2, y2 = [int(v) for v in d.get("xyxy", (0, 0, 0, 0))]
            # Crop the box from the image
            box_img = img.crop((x1, y1, x2, y2))
            try:
                ocr_text = ocr_engine.text(box_img, min_conf=0.3)
                ocr_results[i] = ocr_text.strip()
                if ocr_text.strip():
                    print(f"[{i:02d}] OCR: '{ocr_text.strip()}'")
            except Exception as e:
                print(f"[{i:02d}] OCR failed: {e}")
                ocr_results[i] = ""
    
    print("\n=== Detection Details ===")
    for i, d in enumerate(dets):
        name = d.get("name", "?")
        conf = float(d.get("conf", 0.0))
        x1, y1, x2, y2 = d.get("xyxy", (0, 0, 0, 0))
        ocr_info = f" | OCR: '{ocr_results[i]}'" if i in ocr_results and ocr_results[i] else ""
        print(
            f"[{i:02d}] {name:<20} conf={conf:0.3f}  xyxy=({x1:0.1f},{y1:0.1f},{x2:0.1f},{y2:0.1f}){ocr_info}"
        )

    # Draw overlay and save
    ov = _draw_overlay(img, dets, ocr_results)
    out_path = Path(args.save or "./debug_nav_overlay.png").resolve()
    ov.save(out_path)
    print(f"\nSaved overlay -> {out_path}")
    img.save("save.png")

if __name__ == "__main__":
    # python capture_nav_debug.py  --mode scrcpy --window-title "23117RA68G" --conf 0.10
    main()
