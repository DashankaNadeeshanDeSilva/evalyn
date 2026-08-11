"""The `evalyn ui` cockpit — a local FastAPI server over the `runs/` directory.

Deliberately empty. `evalyn.cli` imports names from this package's submodules
lazily, inside the `ui` command body, so `import evalyn.cli` never drags in
fastapi or uvicorn. Anything imported here would defeat that and is asserted
against by a subprocess guard test.
"""
