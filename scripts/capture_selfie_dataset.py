from __future__ import annotations

import argparse
import base64
import json
import re
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parents[1]
TEST_DATASET_ROOT = ROOT / "test_dataset"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DEFAULT_DATASET_GROUPS = {
    "document_print_copy": {
        "path": TEST_DATASET_ROOT / "document_print_copy",
        "label": "Document upload / print-copy",
        "facingMode": "environment",
        "mirror": False,
        "folders": [
            "real_camera_passport",
            "real_camera_lao_id",
            "fake_printed_passport_on_paper",
            "fake_printed_lao_id_on_paper",
            "fake_photocopy_or_scan",
            "fake_screen_display",
            "uncertain_review",
        ],
    },
    "selfie_passive_liveness_face_login": {
        "path": TEST_DATASET_ROOT / "selfie_passive_liveness_face_login",
        "label": "Selfie passive liveness / face match",
        "facingMode": "user",
        "mirror": True,
        "folders": [
            "real_live_match",
            "real_live_nonmatch",
            "real_live_poor_quality",
            "fake_printed_photo",
            "fake_phone_screen_photo",
            "fake_tablet_laptop_screen",
            "fake_video_replay",
            "fake_cutout_or_paper_mask",
            "multiple_faces",
            "no_valid_face",
            "uncertain_review",
        ],
    },
    "active_liveness": {
        "path": TEST_DATASET_ROOT / "active_liveness",
        "label": "Active face liveness",
        "facingMode": "user",
        "mirror": True,
        "folders": [
            "real_live_face",
            "real_live_face_with_glasses",
            "real_live_poor_lighting",
            "fake_phone_screen_replay",
            "fake_tablet_screen_replay",
            "fake_laptop_screen_replay",
            "fake_printed_photo",
            "fake_video_replay_closeup",
            "uncertain_review",
        ],
    },
    "face_login": {
        "path": TEST_DATASET_ROOT / "face_login",
        "label": "Face login",
        "facingMode": "user",
        "mirror": True,
        "folders": [
            "enrolled_real_live",
            "enrolled_screen_replay",
            "enrolled_printed_photo",
            "unknown_real_live",
            "unknown_screen_replay",
            "multiple_faces",
            "no_valid_face",
            "uncertain_review",
        ],
    },
}
IMAGE_RE = re.compile(r"^data:image/(?P<kind>png|jpeg|jpg|webp);base64,(?P<data>.+)$")


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>eKYC Dataset Capture</title>
  <style>
    :root {
      color-scheme: light;
      --navy: #071736;
      --gold: #e6bd24;
      --line: #d9e2f0;
      --muted: #65728b;
      --ok: #0f7a5b;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f4f7fb;
      color: var(--navy);
      display: grid;
      place-items: center;
      padding: 24px;
    }
    main {
      width: min(1120px, 100%);
      display: grid;
      grid-template-columns: minmax(320px, 420px) 1fr;
      gap: 24px;
      align-items: start;
    }
    section {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 24px 60px rgba(7, 23, 54, 0.08);
      padding: 24px;
    }
    h1 {
      font-size: clamp(32px, 5vw, 64px);
      line-height: 0.96;
      margin: 0 0 16px;
      letter-spacing: 0;
    }
    p {
      color: var(--muted);
      font-size: 17px;
      line-height: 1.55;
      margin: 0 0 20px;
    }
    label {
      display: block;
      font-weight: 800;
      margin: 18px 0 8px;
    }
    select, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      color: var(--navy);
      font: inherit;
      font-weight: 700;
      padding: 14px 16px;
      background: #fff;
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-top: 20px;
    }
    button {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px 18px;
      color: var(--navy);
      background: #fff;
      font: inherit;
      font-weight: 900;
      cursor: pointer;
    }
    button.primary {
      background: var(--gold);
      border-color: var(--gold);
    }
    button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .status {
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 10px;
      background: #f4f7fb;
      color: var(--muted);
      font-weight: 800;
      min-height: 52px;
    }
    .status.ok { color: var(--ok); }
    .status.error { color: var(--danger); }
    .folder-count {
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffaf0;
      padding: 14px 16px;
      color: var(--navy);
      font-weight: 900;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .folder-count span {
      color: var(--muted);
      font-size: 0.94rem;
      font-weight: 800;
    }
    .folder-count strong {
      color: var(--ok);
      font-size: 1.45rem;
      line-height: 1;
      white-space: nowrap;
    }
    .preview {
      padding: 0;
      overflow: hidden;
      background: var(--navy);
      min-height: 520px;
      display: grid;
      place-items: center;
      position: relative;
    }
    video {
      width: 100%;
      height: 100%;
      min-height: 520px;
      object-fit: cover;
      background: #071736;
    }
    video.mirrored { transform: scaleX(-1); }
    .badge {
      position: absolute;
      top: 18px;
      left: 18px;
      background: rgba(255,255,255,0.92);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 16px;
      font-weight: 900;
      font-size: 1.06rem;
      border-color: rgba(217, 174, 39, 0.65);
    }
    .countdown {
      position: absolute;
      inset: 0;
      display: none;
      place-items: center;
      background: rgba(7, 23, 54, 0.22);
      color: #fff;
      font-size: clamp(96px, 18vw, 220px);
      font-weight: 950;
      line-height: 1;
      text-shadow: 0 18px 50px rgba(7, 23, 54, 0.55);
      pointer-events: none;
      z-index: 2;
    }
    .countdown.active {
      display: grid;
      animation: countdownPulse 0.72s ease both;
    }
    @keyframes countdownPulse {
      from { transform: scale(0.82); opacity: 0; }
      35% { opacity: 1; }
      to { transform: scale(1); opacity: 1; }
    }
    .shot-number {
      position: absolute;
      right: 22px;
      bottom: 16px;
      display: none;
      color: #e7bf35;
      font-size: clamp(64px, 9vw, 120px);
      font-weight: 950;
      line-height: 1;
      text-shadow: 0 12px 36px rgba(7, 23, 54, 0.75);
      pointer-events: none;
      z-index: 1;
    }
    .shot-number.active {
      display: block;
      animation: shotPop 1.4s ease both;
    }
    @keyframes shotPop {
      from { transform: scale(1.4); opacity: 0; }
      18% { transform: scale(1); opacity: 1; }
      85% { opacity: 1; }
      to { transform: scale(0.96); opacity: 0; }
    }
    canvas { display: none; }
    @media (max-width: 820px) {
      main { grid-template-columns: 1fr; }
      .preview, video { min-height: 420px; }
    }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>eKYC dataset capture</h1>
      <p>Choose the main dataset, then choose the label folder inside it. Captures are saved directly into the selected test dataset folder.</p>

      <label for="dataset">Main folder</label>
      <select id="dataset"></select>

      <label for="folder">Nested label folder</label>
      <select id="folder"></select>

      <label for="interval">Capture interval, seconds</label>
      <input id="interval" type="number" min="3" value="3" />

      <div class="actions">
        <button id="start" class="primary">Start</button>
        <button id="stop" disabled>Stop</button>
      </div>

      <div id="folderCount" class="folder-count" aria-live="polite">
        <span>Selected folder images</span>
        <strong>Checking...</strong>
      </div>

      <div id="status" class="status">Camera is idle.</div>
    </section>

    <section class="preview">
      <div id="badge" class="badge">This batch: 0</div>
      <video id="video" autoplay playsinline muted></video>
      <div id="countdown" class="countdown" aria-live="polite"></div>
      <div id="shotNumber" class="shot-number" aria-live="polite"></div>
      <canvas id="canvas"></canvas>
    </section>
  </main>

  <script>
    const datasets = __DATASETS__;
    const datasetSelect = document.getElementById("dataset");
    const folderSelect = document.getElementById("folder");
    const intervalInput = document.getElementById("interval");
    const startButton = document.getElementById("start");
    const stopButton = document.getElementById("stop");
    const folderCountBox = document.getElementById("folderCount");
    const statusBox = document.getElementById("status");
    const badge = document.getElementById("badge");
    const video = document.getElementById("video");
    const countdown = document.getElementById("countdown");
    const shotNumber = document.getElementById("shotNumber");
    const canvas = document.getElementById("canvas");

    let stream = null;
    let captureLoopActive = false;
    let captured = 0;
    let folderTotal = null;
    let countTimer = null;
    let countRequestKey = "";

    function updateBadge() {
      const folderPart = folderTotal === null ? "" : ` · Folder total: ${folderTotal}`;
      badge.textContent = `This batch: ${captured}${folderPart}`;
    }

    function updateFolderCountDisplay(total, state = "ok") {
      const strong = folderCountBox.querySelector("strong");
      if (!strong) return;
      if (state === "loading") {
        strong.textContent = "Checking...";
        strong.style.color = "var(--muted)";
        return;
      }
      if (state === "error") {
        strong.textContent = "Unavailable";
        strong.style.color = "var(--danger)";
        return;
      }
      const count = Number(total || 0);
      strong.textContent = `${count} image${count === 1 ? "" : "s"}`;
      strong.style.color = "var(--ok)";
    }

    async function refreshFolderCount() {
      const dataset = datasetSelect.value;
      const folder = folderSelect.value;
      if (!dataset || !folder) return;
      const requestKey = `${dataset}/${folder}`;
      countRequestKey = requestKey;
      try {
        const params = new URLSearchParams({ dataset, folder });
        const response = await fetch(`/count?${params.toString()}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Could not count folder images");
        }
        if (countRequestKey !== requestKey) return;
        folderTotal = payload.folder_total ?? 0;
        updateFolderCountDisplay(folderTotal);
        updateBadge();
      } catch (error) {
        if (countRequestKey !== requestKey) return;
        updateFolderCountDisplay(null, "error");
      }
    }

    function restartCountPolling() {
      if (countTimer) {
        clearInterval(countTimer);
      }
      updateFolderCountDisplay(null, "loading");
      refreshFolderCount();
      countTimer = setInterval(refreshFolderCount, 2000);
    }

    for (const dataset of datasets) {
      const option = document.createElement("option");
      option.value = dataset.key;
      option.textContent = dataset.label;
      datasetSelect.appendChild(option);
    }

    function selectedDataset() {
      return datasets.find((dataset) => dataset.key === datasetSelect.value) || datasets[0];
    }

    function populateFolders() {
      const dataset = selectedDataset();
      folderSelect.innerHTML = "";
      for (const folder of dataset.folders) {
        const option = document.createElement("option");
        option.value = folder;
        option.textContent = folder;
        folderSelect.appendChild(option);
      }
      video.classList.toggle("mirrored", dataset.mirror);
      setStatus(`Selected ${dataset.label}. Saving to ${dataset.key}/${folderSelect.value}`);
      restartCountPolling();
    }

    for (const folder of selectedDataset().folders) {
      const option = document.createElement("option");
      option.value = folder;
      option.textContent = folder;
      folderSelect.appendChild(option);
    }
    populateFolders();
    datasetSelect.addEventListener("change", populateFolders);
    folderSelect.addEventListener("change", () => {
      setStatus(`Selected ${selectedDataset().label}. Saving to ${datasetSelect.value}/${folderSelect.value}`);
      restartCountPolling();
    });

    function setStatus(text, kind = "") {
      statusBox.textContent = text;
      statusBox.className = `status ${kind}`.trim();
    }

    async function openCamera() {
      const dataset = selectedDataset();
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: dataset.facingMode },
          width: { ideal: 1280 },
          height: { ideal: 720 }
        },
        audio: false
      });
      video.srcObject = stream;
      await video.play();
    }

    async function captureOne() {
      if (!captureLoopActive) return;
      if (!stream || !video.videoWidth || !video.videoHeight) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      const dataset = selectedDataset();
      if (dataset.mirror) {
        context.translate(canvas.width, 0);
        context.scale(-1, 1);
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const image = canvas.toDataURL("image/jpeg", 0.92);

      const response = await fetch("/capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset: datasetSelect.value, folder: folderSelect.value, image })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Capture failed");
      }
      captured += 1;
      folderTotal = payload.folder_total ?? null;
      updateFolderCountDisplay(folderTotal);
      updateBadge();
      showShotNumber(captured);
      setStatus(`Saved #${captured}: ${payload.filename}`, "ok");
    }

    function sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function showCountdown(value) {
      countdown.textContent = value;
      countdown.classList.remove("active");
      void countdown.offsetWidth;
      countdown.classList.add("active");
    }

    function hideCountdown() {
      countdown.classList.remove("active");
      countdown.textContent = "";
    }

    function showShotNumber(value) {
      shotNumber.textContent = value;
      shotNumber.classList.remove("active");
      void shotNumber.offsetWidth;
      shotNumber.classList.add("active");
    }

    function hideShotNumber() {
      shotNumber.classList.remove("active");
      shotNumber.textContent = "";
    }

    async function waitWithCountdown(intervalSeconds) {
      const leadSeconds = Math.min(3, intervalSeconds);
      const quietSeconds = Math.max(0, intervalSeconds - leadSeconds);
      if (quietSeconds > 0) {
        setStatus(`Next capture in ${intervalSeconds}s`);
        await sleep(quietSeconds * 1000);
      }
      for (let value = leadSeconds; value >= 1; value -= 1) {
        if (!captureLoopActive) return false;
        showCountdown(value);
        setStatus(`Capturing in ${value}...`);
        await sleep(1000);
      }
      hideCountdown();
      return captureLoopActive;
    }

    async function runCaptureLoop(intervalSeconds) {
      while (captureLoopActive) {
        const shouldCapture = await waitWithCountdown(intervalSeconds);
        if (!shouldCapture) return;
        await captureOne();
      }
    }

    startButton.addEventListener("click", async () => {
      try {
        startButton.disabled = true;
        datasetSelect.disabled = true;
        folderSelect.disabled = true;
        intervalInput.disabled = true;
        captured = 0;
        folderTotal = null;
        updateBadge();
        hideShotNumber();
        setStatus("Opening front camera...");
        await openCamera();
        const intervalSeconds = Math.max(3, Number(intervalInput.value) || 3);
        intervalInput.value = String(intervalSeconds);
        captureLoopActive = true;
        stopButton.disabled = false;
        setStatus(`Capturing every ${intervalSeconds}s into ${datasetSelect.value}/${folderSelect.value}`, "ok");
        runCaptureLoop(intervalSeconds).catch((error) => {
          captureLoopActive = false;
          hideCountdown();
          setStatus(error.message || String(error), "error");
          startButton.disabled = false;
          stopButton.disabled = true;
          datasetSelect.disabled = false;
          folderSelect.disabled = false;
          intervalInput.disabled = false;
        });
      } catch (error) {
        setStatus(error.message || String(error), "error");
        hideCountdown();
        startButton.disabled = false;
        datasetSelect.disabled = false;
        folderSelect.disabled = false;
        intervalInput.disabled = false;
      }
    });

    stopButton.addEventListener("click", () => {
      captureLoopActive = false;
      hideCountdown();
      hideShotNumber();
      if (stream) {
        for (const track of stream.getTracks()) track.stop();
      }
      stream = null;
      video.srcObject = null;
      startButton.disabled = false;
      stopButton.disabled = true;
      datasetSelect.disabled = false;
      folderSelect.disabled = false;
      intervalInput.disabled = false;
      const folderPart = folderTotal === null ? "" : ` Folder now has ${folderTotal} images.`;
      setStatus(`Batch finished: ${captured} image${captured === 1 ? "" : "s"} saved to ${datasetSelect.value}/${folderSelect.value}.${folderPart}`, "ok");
      refreshFolderCount();
    });
  </script>
</body>
</html>
"""


class CaptureServer(BaseHTTPRequestHandler):
    datasets: dict[str, dict[str, object]]

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/count":
            query = parse_qs(parsed.query)
            dataset = query.get("dataset", [""])[0]
            folder = query.get("folder", [""])[0]
            try:
                folder_total = self.count_images(dataset, folder)
                self.send_json({"folder_total": folder_total})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = HTML.replace("__DATASETS__", json.dumps(self.public_datasets())).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/capture":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            dataset = str(payload.get("dataset", ""))
            folder = str(payload.get("folder", ""))
            image = str(payload.get("image", ""))
            saved = self.save_capture(dataset, folder, image)
            folder_total = self.count_images(dataset, folder)
            self.send_json({"filename": saved.name, "path": str(saved), "folder_total": folder_total})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    @classmethod
    def public_datasets(cls) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for key, config in cls.datasets.items():
            output.append(
                {
                    "key": key,
                    "label": config["label"],
                    "folders": config["folders"],
                    "facingMode": config["facingMode"],
                    "mirror": config["mirror"],
                }
            )
        return output

    def save_capture(self, dataset: str, folder: str, image: str) -> Path:
        target_dir = self.target_folder(dataset, folder)

        match = IMAGE_RE.match(image)
        if not match:
            raise ValueError("Invalid image payload")

        kind = "jpg" if match.group("kind") in {"jpeg", "jpg"} else match.group("kind")
        data = base64.b64decode(match.group("data"), validate=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{timestamp}.{kind}"
        target.write_bytes(data)
        return target

    def target_folder(self, dataset: str, folder: str) -> Path:
        config = self.datasets.get(dataset)
        if config is None:
            raise ValueError("Unknown main dataset folder")
        folders = config["folders"]
        if not isinstance(folders, list) or folder not in folders:
            raise ValueError("Unknown target folder")

        dataset_path = config["path"]
        if not isinstance(dataset_path, Path):
            raise ValueError("Invalid dataset path")
        return dataset_path / folder

    def count_images(self, dataset: str, folder: str) -> int:
        target_dir = self.target_folder(dataset, folder)
        target_dir.mkdir(parents=True, exist_ok=True)
        return sum(1 for item in target_dir.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES)

    def send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def ensure_default_dataset_groups() -> dict[str, dict[str, object]]:
    datasets: dict[str, dict[str, object]] = {}
    for key, raw_config in DEFAULT_DATASET_GROUPS.items():
        dataset_path = raw_config["path"]
        folders = raw_config["folders"]
        assert isinstance(dataset_path, Path)
        assert isinstance(folders, list)
        dataset_path.mkdir(parents=True, exist_ok=True)
        for folder in folders:
            folder_path = dataset_path / str(folder)
            folder_path.mkdir(parents=True, exist_ok=True)
            gitkeep = folder_path / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.write_text("", encoding="utf-8")
        datasets[key] = {
            "path": dataset_path,
            "label": raw_config["label"],
            "facingMode": raw_config["facingMode"],
            "mirror": raw_config["mirror"],
            "folders": folders,
        }
    return datasets


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture eKYC test dataset images from a browser camera.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    datasets = ensure_default_dataset_groups()
    CaptureServer.datasets = datasets

    server = ThreadingHTTPServer((args.host, args.port), CaptureServer)
    print("Datasets:")
    for key, config in datasets.items():
        print(f"  {key}: {config['path']}")
    print(f"Open: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop the capture server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping capture server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
