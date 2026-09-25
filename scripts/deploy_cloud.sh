#!/usr/bin/env bash
set -e

echo "=== 1. Installing System Dependencies ==="
apt-get update && apt-get install -y \
    git \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    jq \
    curl

WORKSPACE_DIR="/workspace"
mkdir -p "${WORKSPACE_DIR}"
cd "${WORKSPACE_DIR}"

echo "=== 2. Cloning ComfyUI Core ==="
if [ ! -d "ComfyUI" ]; then
    git clone https://github.com/comfyanonymous/ComfyUI.git
fi
cd ComfyUI

echo "=== 3. Setting Up Virtual Environment & Base Dependencies ==="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 4. Auto-Installing Custom Nodes from Manifest ==="
MANIFEST_PATH="../custom_nodes.json"
if [ -f "$MANIFEST_PATH" ]; then
    cd custom_nodes
    jq -c '.[]' "$MANIFEST_PATH" | while read -r node; do
        URL=$(echo "$node" | jq -r '.url')
        NAME=$(echo "$node" | jq -r '.name')
        if [ ! -d "$NAME" ]; then
            echo "Cloning custom node: $NAME"
            git clone "$URL" "$NAME"
            if [ -f "$NAME/requirements.txt" ]; then
                pip install -r "$NAME/requirements.txt"
            fi
        fi
    done
    cd ..
fi

echo "=== 5. Starting ComfyUI API Server ==="
python main.py --listen 0.0.0.0 --port 8188