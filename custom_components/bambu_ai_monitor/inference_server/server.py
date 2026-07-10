"""YOLO inference server for Bambu AI Print Monitor.

Runs on the HOST machine (not in the HA container) and listens for
image analysis requests from the HA component via HTTP.

Usage (on host, not in container):
    # Install dependencies once
    pip3 install onnxruntime pillow numpy

    # Run server
    python3 inference_server/server.py [--port 19530] [--model /path/to/model.onnx]
"""

import argparse
import json
import io
import logging
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys

import numpy as np
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="[YOLO] %(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("yolo-server")

# Default paths
DEFAULT_MODEL = "best.onnx"
DEFAULT_PORT = 19530

# YOLO classes (single-class: spaghetti only)
YOLO_CLASS_NAMES = ["spaghetti"]
YOLO_ANOMALY_TYPE_MAP = {
    "spaghetti": "spaghetti",
}

INPUT_SIZE = 640
NMS_IOU_THRESHOLD = 0.45
NMS_CONF_THRESHOLD = 0.25

# Visualize confidence threshold (only draw boxes above this)
VISUALIZE_CONF_THRESHOLD = 0.5


class YOLOHandler(BaseHTTPRequestHandler):
    """HTTP handler for YOLO inference requests."""

    # Shared across all requests
    session = None
    model_path = None

    def do_GET(self):
        if self.path == "/health":
            self._handle_health()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/analyze":
            self._handle_analyze()
        elif self.path == "/visualize":
            self._handle_visualize()
        elif self.path == "/health":
            self._handle_health()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_health(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        status = "ok" if self.session is not None else "model_not_loaded"
        self.wfile.write(json.dumps({"status": status}).encode())

    def _handle_analyze(self):
        """Run YOLO inference on uploaded image."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_error("No image data")
                return

            image_bytes = self.rfile.read(content_length)

            # Load model (lazy)
            if self.session is None:
                self._load_model()

            # Run inference
            result = self._run_inference(image_bytes)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        except Exception as e:
            log.error("Inference error: %s", e)
            self._send_error(str(e))

    def _send_error(self, message: str):
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "error": message,
            "anomaly_detected": False,
            "anomaly_type": "none",
            "confidence": 0.0,
            "description": f"服务器错误: {message}",
        }).encode())

    def _load_model(self):
        """Load ONNX model and warm up."""
        import onnxruntime as ort

        resolved = self.model_path
        if not Path(resolved).exists():
            raise FileNotFoundError(f"Model not found: {resolved}")

        log.info("Loading model: %s", resolved)
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # Use all CPU cores for Orange Pi
        opts.intra_op_num_threads = 4

        self.session = ort.InferenceSession(
            resolved, opts, providers=["CPUExecutionProvider"],
        )
        log.info("Model loaded, warming up...")

        # Warm-up: run a dummy inference to trigger graph optimization
        dummy = np.random.randn(1, 3, INPUT_SIZE, INPUT_SIZE).astype(np.float32)
        input_name = self.session.get_inputs()[0].name
        self.session.run(None, {input_name: dummy})
        log.info("Warm-up complete")

    def _run_detection(self, image_bytes: bytes) -> tuple[Image.Image, list[dict]]:
        """Run YOLO inference, return (original_image, detections)."""
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")

        orig_w, orig_h = image.size

        # Preprocess
        image_resized, ratio, pad = self._letterbox(image)
        img_array = np.array(image_resized, dtype=np.float32) / 255.0
        img_array = np.transpose(img_array, (2, 0, 1))[np.newaxis, :, :, :]

        # Inference
        input_name = self.session.get_inputs()[0].name
        outputs = self.session.run(None, {input_name: img_array})

        # Postprocess
        detections = self._postprocess(outputs[0], orig_w, orig_h, ratio, pad)
        return image, detections

    def _run_inference(self, image_bytes: bytes) -> dict:
        """Run YOLO inference and return result dict."""
        image, detections = self._run_detection(image_bytes)

        if not detections:
            return {
                "anomaly_detected": False,
                "anomaly_type": "none",
                "confidence": 0.0,
                "description": "未检测到异常",
            }

        best = max(detections, key=lambda d: d["confidence"])
        class_name = best["class_name"]
        anomaly_type = YOLO_ANOMALY_TYPE_MAP.get(class_name, "other")

        log.info("Detected: %s (conf=%.4f)", class_name, best["confidence"])

        return {
            "anomaly_detected": True,
            "anomaly_type": anomaly_type,
            "confidence": best["confidence"],
            "description": f"检测到 {class_name} (置信度: {best['confidence']:.1%})",
        }

    def _handle_visualize(self):
        """Run YOLO inference and return annotated image with bounding boxes."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No image data")
                return

            image_bytes = self.rfile.read(content_length)

            # Load model (lazy)
            if self.session is None:
                self._load_model()

            image, detections = self._run_detection(image_bytes)

            # Draw bounding boxes
            from PIL import ImageDraw, ImageFont

            draw = ImageDraw.Draw(image)
            # Try to get a font, fall back to default
            font = None
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
            except (IOError, OSError):
                try:
                    font = ImageFont.load_default()
                except Exception:
                    pass

            box_colors = {
                "spaghetti": "#FF4444",
            }

            for det in detections:
                conf = det["confidence"]
                # Only draw boxes above visualize threshold
                if conf < VISUALIZE_CONF_THRESHOLD:
                    continue
                x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
                # Guard against invalid bbox
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
                cls_name = det["class_name"]
                color = box_colors.get(cls_name, "#FF4444")

                # Draw box
                draw.rectangle([x1, y1, x2, y2], outline=color, width=3)

                # Draw label background
                label = f"{cls_name} {conf:.0%}"
                label_bbox = draw.textbbox((0, 0), label, font=font)
                label_w = label_bbox[2] - label_bbox[0]
                label_h = label_bbox[3] - label_bbox[1]
                label_top = max(0, y1 - label_h - 4)
                draw.rectangle(
                    [x1, label_top, x1 + label_w + 8, y1],
                    fill=color,
                )

                # Draw label text
                draw.text((x1 + 4, label_top + 2), label, fill="white", font=font)

            # Save annotated image to bytes
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85)
            annotated_bytes = output.getvalue()

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(annotated_bytes)))
            self.end_headers()
            self.wfile.write(annotated_bytes)

        except Exception as e:
            log.error("Visualize error: %s", e)
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode())

    @staticmethod
    def _letterbox(image: Image.Image) -> tuple[Image.Image, float, tuple[int, int]]:
        orig_w, orig_h = image.size
        ratio = min(INPUT_SIZE / orig_w, INPUT_SIZE / orig_h)
        new_w = int(orig_w * ratio)
        new_h = int(orig_h * ratio)

        resized = image.resize((new_w, new_h), Image.LANCZOS)
        img_np = np.array(resized)

        pad_w = (INPUT_SIZE - new_w) // 2
        pad_h = (INPUT_SIZE - new_h) // 2

        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        padded[pad_h:pad_h + new_h, pad_w:pad_w + new_w] = img_np

        return Image.fromarray(padded), ratio, (pad_w, pad_h)

    @staticmethod
    def _postprocess(predictions: np.ndarray, orig_w: int, orig_h: int,
                     ratio: float, pad: tuple[int, int]) -> list[dict]:
        num_classes = len(YOLO_CLASS_NAMES)
        pred = np.squeeze(predictions, axis=0)
        pred = np.transpose(pred)
        box_data = pred[:, :4]
        cls_scores = pred[:, 4:]
        # YOLOv8 ONNX 导出已包含 sigmoid，不需要再算
        max_scores = cls_scores.max(axis=1)
        max_classes = cls_scores.argmax(axis=1)

        keep = max_scores >= NMS_CONF_THRESHOLD
        if not keep.any():
            return []

        box_data = box_data[keep]
        max_scores = max_scores[keep]
        max_classes = max_classes[keep]

        boxes_xyxy = []
        for i in range(len(box_data)):
            cx, cy, w, h = box_data[i]
            # YOLOv8 ONNX 输出的坐标已经是像素值 (0~640)，不需要再乘 INPUT_SIZE
            cx_orig = (cx - pad[0]) / ratio
            cy_orig = (cy - pad[1]) / ratio
            w_orig = w / ratio
            h_orig = h / ratio
            x1 = max(0, cx_orig - w_orig / 2)
            y1 = max(0, cy_orig - h_orig / 2)
            x2 = min(orig_w, cx_orig + w_orig / 2)
            y2 = min(orig_h, cy_orig + h_orig / 2)
            boxes_xyxy.append([x1, y1, x2, y2])

        boxes_xyxy = np.array(boxes_xyxy, dtype=np.float32)
        indices = _nms(boxes_xyxy, max_scores, NMS_IOU_THRESHOLD)

        results = []
        for idx in indices:
            cls_id = int(max_classes[idx])
            results.append({
                "class_id": cls_id,
                "class_name": YOLO_CLASS_NAMES[cls_id],
                "confidence": float(max_scores[idx]),
                "bbox": boxes_xyxy[idx].tolist(),
            })
        return results

    def log_message(self, format, *args):
        """Suppress default HTTP log."""
        pass


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    if len(boxes) == 0:
        return []
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while len(order) > 0:
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        inter = inter_w * inter_h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]
    return keep


def main():
    parser = argparse.ArgumentParser(description="YOLO inference server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    # Resolve model path: try current dir, then script dir
    model_path = Path(args.model)
    if not model_path.exists():
        alt = Path(__file__).parent / args.model
        if alt.exists():
            model_path = alt
        else:
            log.error("Model not found: %s (also tried: %s)", model_path, alt)
            sys.exit(1)

    YOLOHandler.model_path = str(model_path)
    server = HTTPServer(("0.0.0.0", args.port), YOLOHandler)
    log.info("YOLO inference server started on port %s", args.port)
    log.info("Model: %s", YOLOHandler.model_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped")
        server.server_close()


if __name__ == "__main__":
    main()
