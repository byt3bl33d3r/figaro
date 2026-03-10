# TODO

## ML Model Inference on Desktop Streams

Run ML models (e.g. facial recognition, omniparser) on all connected worker desktop streams.

### Approach 1: Client-side (Browser) — WebGL/WASM

Capture frames from the Guacamole `<canvas>` element and run inference in-browser.

- **Frame capture**: Each `VNCViewer` component has a Guacamole `Display` with a canvas. Use `canvas.toDataURL()` or `getImageData()` on a timer/`requestAnimationFrame`
- **Inference**: TensorFlow.js, ONNX Runtime Web, or MediaPipe (built-in face detection) — all run on WebGL/WebGPU
- **Pros**: No server infrastructure needed, scales with client hardware, low latency
- **Cons**: Hammers the user's GPU/CPU, doesn't scale well with many streams (N canvases x inference per frame), model size limited by browser memory

```
Canvas → getImageData() → tf.js/ONNX Runtime → overlay results on canvas
```

### Approach 2: Server-side ML Service (Recommended)

New `figaro-ml/` service that captures frames via `asyncvnc` and runs inference server-side, publishing results via NATS.

- **Frame capture**: Two options:
  - **At guapy level**: Middleware in the orchestrator's Guacamole WebSocket tunnel that intercepts Guacamole `img` instructions, decodes the frame, runs inference, and annotates
  - **Direct VNC capture**: A dedicated service connects to worker VNC servers (like `vnc_client.py` already does with `asyncvnc`) and captures frames independently of the UI
- **Inference**: PyTorch, ONNX Runtime (GPU), or a dedicated inference service
- **Results delivery**: Publish annotations to NATS, UI subscribes and renders overlays on the canvas
- **Pros**: GPU acceleration on server, doesn't affect UI performance, works even when no UI is open, single inference per stream regardless of viewer count
- **Cons**: Adds server load, needs GPU infrastructure

```
                          ┌─────────────────┐
  guacd ──VNC frames──→  │  ML Service      │ ──NATS──→ UI overlay
                          │  (GPU inference) │
                          └─────────────────┘
  OR
  asyncvnc ──snapshots──→ ML Service ──NATS──→ UI overlay
```

**Proposed structure:**
```
figaro-ml/
├── src/
│   ├── service.py          # NATS-connected service
│   ├── capture.py          # asyncvnc frame capture
│   ├── models/
│   │   ├── base.py         # Model interface
│   │   └── face_detect.py  # Facial recognition model
│   └── config.py           # FIGARO_ML_* env vars
```

**NATS subjects:**
```
figaro.ml.{worker_id}.detections   # JetStream - detection results
figaro.api.ml.start                # Start ML on a worker stream
figaro.api.ml.stop                 # Stop ML on a worker stream
figaro.api.ml.models               # List available models
```

**UI side:** Zustand store for detections, subscribe to JetStream subject, render SVG/canvas overlays on top of Guacamole display in `VNCViewer`.

**Frame rate:** 2-5fps via `asyncvnc` is sufficient for facial recognition — keeps load manageable with many workers.

### Approach 3: Hybrid — Best of Both

- **Server** handles heavy models (facial recognition, object detection) at lower FPS (1-5 fps)
- **Browser** handles lightweight real-time overlays (bounding box rendering, tracking between server keyframes)
- Results flow via NATS, which is already wired up

```
  ┌───────────────────────────────────────────────────────┐
  │                      Browser                          │
  │  Canvas ← Guacamole    +    Overlay ← lightweight     │
  │                              tracking (tf.js)         │
  └──────────────────────────┬────────────────────────────┘
                             │ NATS (detections)
                 ┌───────────┴───────────┐
                 │    figaro-ml service   │
                 │  heavy models (2-5fps) │
                 │  asyncvnc capture      │
                 └───────────────────────┘
```

### GPU / Docker Considerations

- **Metal (Apple GPU) does not work in Docker.** Docker on macOS runs a Linux VM with no access to Metal.
- **Dev on Apple Silicon:** Run ML service natively on macOS using `mlx`, CoreML, or PyTorch MPS backend (`device="mps"`), connect to NATS in Docker via exposed port.
- **CPU-only in Docker:** Works everywhere, slower. ONNX Runtime CPU or PyTorch CPU is feasible for lightweight models (SCRFD, YuNet) at low FPS.
- **Production (Linux + NVIDIA):** Use `nvidia-container-toolkit` + CUDA-enabled Docker images. Standard production approach.

```
# Dev: native macOS + Docker NATS
figaro-ml (native, Metal/MPS) ──→ nats://localhost:4222 (Docker)

# Prod: everything in Docker on Linux
figaro-ml (Docker, CUDA) ──→ nats://nats:4222 (Docker)
```
