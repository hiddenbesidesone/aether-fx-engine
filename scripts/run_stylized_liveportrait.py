import json
import os
import sys
import time
import urllib.parse
import urllib.request
import websocket

COMFY_HOST = "127.0.0.1:8188"
INPUT_DIR = "/workspace/ComfyUI/input"
OUTPUT_DIR = "/workspace/ComfyUI/output"
WORKFLOW_FILE = "/workspace/aether-fx-engine/workflows/liveportrait_stylized_api.json"

def queue_prompt(workflow_dict):
    payload = json.dumps({"prompt": workflow_dict}).encode("utf-8")
    req = urllib.request.Request(f"http://{COMFY_HOST}/prompt", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))

def wait_for_completion(prompt_id):
    ws = websocket.WebSocket()
    ws.connect(f"ws://{COMFY_HOST}/ws?clientId=aether_runner")
    print(f"[*] Task queued (ID: {prompt_id}). Processing frames...")

    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            msg_type = message.get("type")

            if msg_type == "progress":
                val = message["data"]["value"]
                max_val = message["data"]["max"]
                print(f"\r[>] Processing: {val}/{max_val} frames ({(val/max_val)*100:.1f}%)", end="", flush=True)

            elif msg_type == "executing" and message["data"]["node"] is None:
                if message["data"]["prompt_id"] == prompt_id:
                    print("\n[✓] Video generation & audio muxing complete.")
                    break
            elif msg_type == "execution_error":
                print(f"\n[!] Execution Error: {message['data']}")
                sys.exit(1)

def run():
    if not os.path.exists(WORKFLOW_FILE):
        print(f"Workflow file not found at {WORKFLOW_FILE}")
        sys.exit(1)

    # Ensure demo/input assets exist
    os.makedirs(INPUT_DIR, exist_ok=True)
    source_img = os.path.join(INPUT_DIR, "source_doll.png")
    driving_vid = os.path.join(INPUT_DIR, "driving_monologue.mp4")

    if not os.path.exists(source_img) or not os.path.exists(driving_vid):
        print(f"[!] Place your input files in {INPUT_DIR}:")
        print(f"    - {source_img}")
        print(f"    - {driving_vid}")
        sys.exit(1)

    with open(WORKFLOW_FILE, "r") as f:
        workflow = json.load(f)

    prompt_res = queue_prompt(workflow)
    prompt_id = prompt_res.get("prompt_id")
    wait_for_completion(prompt_id)

if __name__ == "__main__":
    run()