"""Load ComfyUI API-format templates and modify them by node title.

Templates address nodes by ``_meta.title`` rather than numeric id, so a template can be
re-exported from the ComfyUI editor (Export (API)) without breaking the CLIs as long
as the titles are kept.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "workflows" / "templates"

# Inputs the server validates by file existence rather than its combo list
# (LoadImage only lists top-level input files, but accepts "subfolder/name").
DYNAMIC_COMBOS = {("LoadImage", "image"), ("LoadAudio", "audio"), ("VHS_LoadVideo", "video")}


class PayloadError(ValueError):
    pass


def is_link(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
            and isinstance(value[1], int))


class WorkflowTemplate:
    def __init__(self, graph: dict[str, dict], name: str = "workflow"):
        self.graph = copy.deepcopy(graph)
        self.name = name

    @classmethod
    def load(cls, path: Path | str) -> "WorkflowTemplate":
        path = Path(path)
        if not path.is_absolute() and not path.exists():
            path = TEMPLATES_DIR / path
        with path.open() as fh:
            graph = json.load(fh)
        if "nodes" in graph and "links" in graph:
            raise PayloadError(f"{path} is a UI workflow; re-export it with 'Export (API)'")
        return cls(graph, name=path.stem)

    # --------------------------------------------------------------- lookup

    def node_id(self, title: str) -> str:
        matches = [nid for nid, node in self.graph.items() if node.get("_meta", {}).get("title") == title]
        if not matches:
            raise PayloadError(f"{self.name}: no node titled {title!r}")
        if len(matches) > 1:
            raise PayloadError(f"{self.name}: several nodes titled {title!r}: {matches}")
        return matches[0]

    def has(self, title: str) -> bool:
        return any(node.get("_meta", {}).get("title") == title for node in self.graph.values())

    def node(self, title: str) -> dict:
        return self.graph[self.node_id(title)]

    # ---------------------------------------------------------------- edits

    def set(self, title: str, **inputs: Any) -> "WorkflowTemplate":
        node = self.node(title)
        for key, value in inputs.items():
            if value is None:
                raise PayloadError(f"{self.name}: refusing to set {title}.{key} to null")
            node["inputs"][key] = value
        return self

    def link(self, title: str, input_name: str, source_title: str, output_index: int = 0) -> "WorkflowTemplate":
        self.node(title)["inputs"][input_name] = [self.node_id(source_title), output_index]
        return self

    def add_node(self, class_type: str, inputs: dict, title: str | None = None) -> str:
        new_id = str(max((int(k) for k in self.graph if k.isdigit()), default=0) + 1)
        self.graph[new_id] = {"class_type": class_type, "inputs": dict(inputs),
                              "_meta": {"title": title or class_type}}
        return new_id

    def remove(self, title: str) -> None:
        nid = self.node_id(title)
        for other_id, node in self.graph.items():
            for key, value in node["inputs"].items():
                if is_link(value) and value[0] == nid:
                    raise PayloadError(f"{self.name}: cannot remove {title!r}; node {other_id}.{key} uses it")
        del self.graph[nid]

    def rewire(self, old: list, new: list, skip: set[str] = frozenset()) -> None:
        """Point every input linked to ``old`` at ``new`` (except nodes in ``skip``)."""
        for nid, node in self.graph.items():
            if nid in skip:
                continue
            for key, value in node["inputs"].items():
                if is_link(value) and value == old:
                    node["inputs"][key] = list(new)

    def insert_lora_chain(self, loras: list[tuple[str, float, float]],
                          checkpoint_title: str = "checkpoint") -> list[str]:
        """Insert chained LoraLoader nodes after the checkpoint loader.

        ``loras`` is a list of (lora_name, strength_model, strength_clip). Every consumer
        of the checkpoint's MODEL (output 0) and CLIP (output 1) is rewired to the last
        LoRA in the chain.
        """
        ckpt = self.node_id(checkpoint_title)
        model_src, clip_src = [ckpt, 0], [ckpt, 1]
        added: list[str] = []
        for i, (name, s_model, s_clip) in enumerate(loras):
            nid = self.add_node("LoraLoader", {
                "model": model_src, "clip": clip_src, "lora_name": name,
                "strength_model": s_model, "strength_clip": s_clip,
            }, title=f"lora_{i}")
            added.append(nid)
            model_src, clip_src = [nid, 0], [nid, 1]
        if added:
            skip = set(added)
            self.rewire([ckpt, 0], model_src, skip)
            self.rewire([ckpt, 1], clip_src, skip)
        return added

    # ----------------------------------------------------------- validation

    def validate(self) -> None:
        """Structural checks that need no server: no nulls, links resolve."""
        problems = []
        for nid, node in self.graph.items():
            if not node.get("class_type"):
                problems.append(f"node {nid} has no class_type")
            for key, value in (node.get("inputs") or {}).items():
                if value is None:
                    problems.append(f"node {nid}.{key} is null")
                elif is_link(value):
                    src = self.graph.get(value[0])
                    if src is None:
                        problems.append(f"node {nid}.{key} links to missing node {value[0]}")
        if problems:
            raise PayloadError(f"{self.name}: " + "; ".join(problems))

    def check_against_server(self, object_info: dict) -> list[str]:
        """Compare the graph with the server's /object_info.

        Returns a list of problems: node classes that are not installed, required inputs
        that are missing, and combo values (model filenames etc.) the server doesn't offer.
        """
        problems = []
        for nid, node in self.graph.items():
            cls = node["class_type"]
            title = node.get("_meta", {}).get("title", cls)
            info = object_info.get(cls)
            if info is None:
                problems.append(f"[{title}] node class {cls!r} is not installed on the server")
                continue
            spec = info.get("input", {})
            required = spec.get("required", {})
            all_inputs = {**required, **spec.get("optional", {})}
            for key in required:
                if key not in node["inputs"]:
                    problems.append(f"[{title}] {cls} is missing required input {key!r}")
            for key, value in node["inputs"].items():
                if is_link(value) or key not in all_inputs or (cls, key) in DYNAMIC_COMBOS:
                    continue
                options = combo_options(all_inputs[key])
                if options is not None and value not in options:
                    shown = ", ".join(map(str, options[:8])) + (" ..." if len(options) > 8 else "")
                    problems.append(f"[{title}] {key}={value!r} not available on server (have: {shown or 'none'})")
        return problems

    def to_api(self) -> dict:
        self.validate()
        return copy.deepcopy(self.graph)

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.graph, indent=2) + "\n")


def combo_options(spec: Any) -> list | None:
    """Extract the allowed values for a combo input in either /object_info format."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options")
    return None
