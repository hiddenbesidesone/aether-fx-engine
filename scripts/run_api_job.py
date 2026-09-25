#!/usr/bin/env python3
import json
import uuid
import os
import argparse
import requests
import websocket # pip install websocket-client

def queue_prompt(prompt_workflow, server_address, client_id):
    """Submits the API JSON workflow payload to ComfyUI."""
    payload = {"prompt": prompt_workflow, "client_id": client_id}
    url = f"http://{server_address}/prompt"
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()

def upload_file(file_path, server_address, subfolder="", overwrite=True):
    """Uploads source video/image or depth pass to ComfyUI's input directory."""
    url = f"http://{server_address}/upload/image"
    filename = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        files = {'image': (filename, f)}
        data = {'subfolder': subfolder, 'overwrite': str(overwrite).lower()}
        res = requests.post(url, files=files, data=data)
        res.raise_for_status()
        return res.json()

def track_progress_and_wait(server_address, client_id, prompt_id):
    """Listens to ComfyUI WebSocket messages to track execution status."""
    ws = websocket.WebSocket()
    ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
    print(f"[*] Connected to ComfyUI WebSocket at {server_address}")
    print(f"[*] Executing prompt_id: {prompt_id}...")

    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            msg_type = message.get("type")

            if msg_type == "progress":
                data = message["data"]
                print(f"   [KSampler Step] {data['value']}/{data['max']}")

            elif msg_type == "executing":
                data = message["data"]
                if data["node"] is None and data["prompt_id"] == prompt_id:
                    print("[✓] Workflow Execution Complete!")
                    break
    ws.close()

def main():
    parser = argparse.ArgumentParser(description="Run a ComfyUI API workflow job.")
    parser.add_argument("--server", default="127.0.0.1:8188", help="ComfyUI server address (e.g. runpod-ip:8188)")
    parser.add_argument("--workflow", required=True, help="Path to API JSON workflow file")
    parser.add_argument("--input_video", help="Optional source video to upload before execution")
    args = parser.parse_args()

    client_id = str(uuid.uuid4())

    # Step 1: Upload input file if specified
    if args.input_video and os.path.exists(args.input_video):
        print(f"[*] Uploading input media: {args.input_video}")
        upload_file(args.input_video, args.server)

    # Step 2: Load API JSON workflow
    with open(args.workflow, 'r') as f:
        workflow_data = json.load(f)

    # Step 3: Submit workflow job
    res = queue_prompt(workflow_data, args.server, client_id)
    prompt_id = res.get("prompt_id")

    # Step 4: Monitor execution over WebSocket
    track_progress_and_wait(args.server, client_id, prompt_id)

if __name__ == "__main__":
    main()