#!/usr/bin/env bash
# Clone (or update) a ComfyUI custom node and install its requirements without letting it
# replace the GPU stack.
#
#   scripts/runpod/safe_node_install.sh <folder-name> <git-url>
#
# - torch / torchvision / torchaudio / xformers / onnxruntime(-gpu) lines are dropped from the
#   node's requirements.txt; everything else installs under pins of the current versions.
# - If the whole file fails to resolve, packages are retried one by one and failures listed,
#   so one unbuildable optional extra doesn't block the rest.
# - Afterwards the CPU onnxruntime wheel is removed if anything pulled it in.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

NAME="${1:?usage: safe_node_install.sh <folder-name> <git-url>}"
URL="${2:?usage: safe_node_install.sh <folder-name> <git-url>}"
DEST="$COMFY_DIR/custom_nodes/$NAME"

if [ -d "$DEST/.git" ]; then
    echo "[*] $NAME already present; pulling latest"
    git -C "$DEST" pull --ff-only || echo "[!] could not fast-forward $NAME; keeping the current checkout"
    git -C "$DEST" submodule update --init --recursive
else
    echo "[*] cloning $NAME"
    git clone --recurse-submodules "$URL" "$DEST"
fi

REQ="$DEST/requirements.txt"
if [ ! -f "$REQ" ]; then
    echo "[✓] $NAME: no requirements.txt"
    exit 0
fi

FILTERED="$STATE_DIR/req_$NAME.txt"
grep -viE '^\s*(torch|torchvision|torchaudio|xformers|onnxruntime|onnxruntime-gpu)\s*([<>=!~;\[]|$)' "$REQ" \
    | grep -vE '^\s*(#|$)' > "$FILTERED" || true
dropped="$(grep -ciE '^\s*(torch|torchvision|torchaudio|xformers|onnxruntime|onnxruntime-gpu)\s*([<>=!~;\[]|$)' "$REQ" || true)"
[ "$dropped" != "0" ] && echo "[*] $NAME: skipped $dropped GPU-stack line(s) from requirements.txt"

if [ -s "$FILTERED" ]; then
    if ! safe_pip -r "$FILTERED"; then
        echo "[!] $NAME: requirements did not resolve together; installing one at a time"
        failed=()
        while IFS= read -r line; do
            safe_pip "$line" || failed+=("$line")
        done < "$FILTERED"
        if [ ${#failed[@]} -gt 0 ]; then
            echo "[!] $NAME: these requirements failed (the node may still load without them):"
            printf '      %s\n' "${failed[@]}"
        fi
    fi
fi

repair_onnxruntime
echo "[✓] $NAME installed"
