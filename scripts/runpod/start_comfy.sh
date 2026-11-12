#!/usr/bin/env bash
# Run after every pod start (and after installing nodes): re-applies the fixes that live
# outside /workspace, then (re)starts ComfyUI on :8188 in the background.
#
#   bash scripts/runpod/start_comfy.sh            # restart ComfyUI
#   bash scripts/runpod/start_comfy.sh --fix-only # only re-apply the fixes
#
# 1. InsightFace models: symlink /root/.insightface/models/buffalo_l -> the copy on /workspace
# 2. Linker paths for the venv's NVIDIA libs (cuDNN / cuBLAS) so onnxruntime-gpu stays on the GPU
# 3. TRELLIS backend choices from check_trellis.py (read only when ComfyUI starts)
# 4. Model caches on /workspace (TORCH_HOME, HF_HOME) -- set in env.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/env.sh"
PORT="${PORT:-8188}"
LOG="${LOG:-/workspace/comfyui.log}"

BUFFALO="$(find /workspace -maxdepth 6 -type d -name buffalo_l -not -path '/root/*' 2>/dev/null | head -n 1 || true)"
if [ -n "$BUFFALO" ]; then
    mkdir -p /root/.insightface/models
    ln -sfn "$BUFFALO" /root/.insightface/models/buffalo_l
    echo "[✓] insightface buffalo_l -> $BUFFALO"
fi

"$PY" -c "import site, glob; print('\n'.join(glob.glob(site.getsitepackages()[0] + '/nvidia/*/lib')))" \
    > /etc/ld.so.conf.d/nvidia-venv.conf
ldconfig
echo "[✓] venv NVIDIA libs registered with ldconfig"

if [ -f "$STATE_DIR/trellis_env.sh" ]; then
    source "$STATE_DIR/trellis_env.sh"
    echo "[✓] TRELLIS: SPARSE_ATTN_BACKEND=$SPARSE_ATTN_BACKEND SPCONV_ALGO=$SPCONV_ALGO"
fi

[ "${1:-}" = "--fix-only" ] && exit 0

RUNNING="main\.py.*--port $PORT|ComfyUI/main\.py|main\.py --listen"
if pgrep -f "$RUNNING" >/dev/null; then
    echo "[*] stopping the running ComfyUI"
    pkill -f "$RUNNING" || true
    for _ in $(seq 1 20); do
        pgrep -f "$RUNNING" >/dev/null || break
        sleep 1
    done
fi

cd "$COMFY_DIR"
nohup "$PY" main.py --listen 0.0.0.0 --port "$PORT" > "$LOG" 2>&1 &
PID=$!
echo "[*] ComfyUI starting (pid $PID, log $LOG)"

for i in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:$PORT/system_stats" >/dev/null; then
        echo "[✓] ComfyUI is up on :$PORT after ${i}s"
        # Import failures of custom nodes are listed at the end of startup.
        grep -A30 "Import times for custom nodes" "$LOG" | grep -i "IMPORT FAILED" \
            && echo "[!] some custom nodes failed to import -- see $LOG" || true
        exit 0
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "[!] ComfyUI exited during startup. Last lines of $LOG:" >&2
        tail -40 "$LOG" >&2
        exit 1
    fi
    sleep 1
done
echo "[!] ComfyUI did not answer on :$PORT within 180s; check $LOG" >&2
exit 1
