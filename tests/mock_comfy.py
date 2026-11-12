"""Minimal in-process ComfyUI stand-in (HTTP + WebSocket) for client and CLI tests."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from pathlib import Path

from aiohttp import WSMsgType, web

TEMPLATES = Path(__file__).resolve().parents[1] / "workflows" / "templates"
FREE_TEXT_INPUTS = {"text", "project_name", "filename_prefix", "background_color"}


def object_info_from_templates() -> dict:
    """Fake /object_info that accepts every class/input/value used by the templates."""
    info: dict = {}
    for path in TEMPLATES.glob("*.json"):
        for node in json.loads(path.read_text()).values():
            entry = info.setdefault(node["class_type"], {"input": {"required": {}, "optional": {}}})
            for key, value in node["inputs"].items():
                if isinstance(value, str) and key not in FREE_TEXT_INPUTS:
                    spec = entry["input"]["required"].setdefault(key, [[]])
                    if value not in spec[0]:
                        spec[0].append(value)
                else:
                    entry["input"]["required"].setdefault(key, ["ANY", {}])
    # Combo choices from IF_Trellis.py that the template only uses one of.
    info["IF_TrellisImageTo3D"]["input"]["required"]["texture_mode"] = [["blank", "fast", "opt"]]
    info["LoraLoader"] = {"input": {"required": {
        "model": ["MODEL"], "clip": ["CLIP"], "lora_name": [["latex_vinyl_v2.safetensors", "gloss.safetensors"]],
        "strength_model": ["FLOAT", {}], "strength_clip": ["FLOAT", {}]}}}
    return info


class MockComfy:
    """Runs jobs instantly. ``outputs_for(workflow)`` decides each job's history outputs;
    ``fail_with`` makes the next job emit execution_error."""

    def __init__(self, device: str = "cuda"):
        self.device = device
        self.uploads: list[tuple[str, str]] = []
        self.prompts: list[dict] = []
        self.history: dict[str, dict] = {}
        self.files: dict[tuple[str, str], bytes] = {}
        self.fail_with: dict | None = None
        self.reject_with: dict | None = None
        self.object_info = object_info_from_templates()
        self.sockets: list[web.WebSocketResponse] = []
        self.loop = asyncio.new_event_loop()
        self.port = None

    # -- lifecycle

    def start(self) -> "MockComfy":
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(self.loop)
            app = web.Application(client_max_size=64 * 1024 * 1024)
            app.add_routes([
                web.get("/system_stats", self.system_stats), web.get("/object_info", self.get_object_info),
                web.post("/upload/image", self.upload), web.post("/prompt", self.prompt),
                web.get("/history/{pid}", self.get_history), web.get("/view", self.view), web.get("/ws", self.ws),
            ])
            self.runner = web.AppRunner(app)
            self.loop.run_until_complete(self.runner.setup())
            site = web.TCPSite(self.runner, "127.0.0.1", 0)
            self.loop.run_until_complete(site.start())
            self.port = site._server.sockets[0].getsockname()[1]
            ready.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(5)
        return self

    def stop(self) -> None:
        async def shutdown():
            for ws in list(self.sockets):
                await ws.close()
            await self.runner.cleanup()

        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # -- handlers

    async def system_stats(self, _):
        return web.json_response({"system": {"comfyui_version": "mock"},
                                  "devices": [{"name": "mock", "type": self.device}]})

    async def get_object_info(self, _):
        return web.json_response(self.object_info)

    async def upload(self, request):
        form = await request.post()
        f = form["image"]
        subfolder = form.get("subfolder", "")
        self.uploads.append((subfolder, f.filename))
        if subfolder:  # VHS_LoadImages offers input subdirectories as combo values
            for cls in self.object_info.values():
                spec = cls["input"]["required"].get("directory")
                if spec and subfolder not in spec[0]:
                    spec[0].append(subfolder)
        return web.json_response({"name": f.filename, "subfolder": subfolder, "type": "input"})

    async def prompt(self, request):
        body = await request.json()
        if self.reject_with:
            return web.json_response(self.reject_with, status=400)
        pid = str(uuid.uuid4())
        self.prompts.append(body["prompt"])
        asyncio.get_running_loop().create_task(self.execute(pid, body["prompt"]))
        return web.json_response({"prompt_id": pid, "number": len(self.prompts), "node_errors": {}})

    async def execute(self, pid, workflow):
        await asyncio.sleep(0.05)
        await self.broadcast({"type": "execution_start", "data": {"prompt_id": pid}})
        for v in (1, 2, 3):
            await self.broadcast({"type": "progress", "data": {"value": v, "max": 3, "prompt_id": pid, "node": "1"}})
        for nid, node in workflow.items():  # the real node crashes before saving the .ply
            if node["class_type"] == "IF_TrellisImageTo3D" and not node["inputs"]["save_glb"]:
                self.fail_with = {"node_id": nid, "node_type": node["class_type"], "exception_type": "AttributeError",
                                  "exception_message": "'NoneType' object has no attribute 'shape'", "traceback": []}
        if self.fail_with:
            data = {"prompt_id": pid, **self.fail_with}
            self.fail_with = None
            self.history[pid] = {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                                          "messages": [["execution_error", data]]}}
            await self.broadcast({"type": "execution_error", "data": data})
            return
        outputs = self.outputs_for(workflow)
        self.history[pid] = {"outputs": outputs, "status": {"status_str": "success", "completed": True,
                                                            "messages": []}}
        await self.broadcast({"type": "executing", "data": {"node": None, "prompt_id": pid}})

    def outputs_for(self, workflow) -> dict:
        outputs = {}
        for nid, node in workflow.items():
            cls, inp = node["class_type"], node["inputs"]
            if cls == "SaveImage":
                n = next((x["inputs"]["amount"] for x in workflow.values() if x["class_type"] == "RepeatLatentBatch"), 1)
                imgs = []
                for i in range(n):
                    sub, _, pre = inp["filename_prefix"].rpartition("/")
                    name = f"{pre}_{i:05d}_.png"
                    self.files[(sub, name)] = b"png"
                    imgs.append({"filename": name, "subfolder": sub, "type": "output"})
                outputs[nid] = {"images": imgs}
            elif cls == "VHS_VideoCombine":
                sub, _, pre = inp["filename_prefix"].rpartition("/")
                self.files[(sub, f"{pre}_00001.mp4")] = b"mp4"
                outputs[nid] = {"gifs": [{"filename": f"{pre}_00001.mp4", "subfolder": sub, "type": "output",
                                          "format": "video/h264-mp4"}]}
            elif cls == "IF_TrellisImageTo3D":
                # Like the real node: the .ply is written to disk but never reported in history.
                proj = inp["project_name"]
                self.files[(proj, f"{proj}.glb")] = b"glb"
                if inp["save_gaussian"]:
                    self.files[(proj, f"{proj}.ply")] = b"ply\nformat binary_little_endian 1.0\n"
            elif cls == "Hy3DExportMesh":
                sub, _, pre = inp["filename_prefix"].rpartition("/")
                self.files[(sub, f"{pre}_00001_.glb")] = b"glb"
                self._hy_path = f"/workspace/ComfyUI/output/{sub}/{pre}_00001_.glb"
        for nid, node in workflow.items():
            if node["class_type"] == "PreviewAny":
                src = workflow[node["inputs"]["source"][0]]
                if src["class_type"] == "IF_TrellisImageTo3D":
                    proj = src["inputs"]["project_name"]
                    outputs[nid] = {"text": [f"{proj}/{proj}.glb"]}
                elif src["class_type"] == "Hy3DExportMesh":
                    outputs[nid] = {"text": [self._hy_path]}
        return outputs

    async def broadcast(self, msg):
        for ws in list(self.sockets):
            if not ws.closed:
                await ws.send_str(json.dumps(msg))

    async def get_history(self, request):
        pid = request.match_info["pid"]
        return web.json_response({pid: self.history[pid]} if pid in self.history else {})

    async def view(self, request):
        key = (request.query.get("subfolder", ""), request.query["filename"])
        if key not in self.files:
            return web.Response(status=404)
        return web.Response(body=self.files[key])

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        await ws.send_str(json.dumps({"type": "status", "data": {"sid": request.query.get("clientId")}}))
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
        self.sockets.remove(ws)
        return ws
