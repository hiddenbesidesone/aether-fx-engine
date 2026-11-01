"""aether-fx-engine: ComfyUI orchestration for 3D, video and stylization workflows."""

__version__ = "0.2.0"

# Lazy exports: env_check must import cleanly inside ComfyUI's venv, which may lack
# the client's dependencies (requests / websocket-client).
_EXPORTS = {
    "ComfyClient": "client",
    "ComfyError": "client",
    "ComfyExecutionError": "client",
    "ComfyValidationError": "client",
    "WorkflowTemplate": "payload_builder",
    "TEMPLATES_DIR": "payload_builder",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        return getattr(importlib.import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
