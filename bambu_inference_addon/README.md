# Bambu Inference Add-on

HA Add-on packaging of `custom_components/bambu_ai_monitor/inference_server/server.py`.
For HA OS / Supervised users without a Docker socket: install once from the
Add-on Store, enable *Start on boot* — no SSH, no `systemd`, no host commands.

## Sync rule

`server.py` here must stay identical to
`../custom_components/bambu_ai_monitor/inference_server/server.py`.
After editing either file, copy it over:

```bash
cp custom_components/bambu_ai_monitor/inference_server/server.py \
   bambu_inference_addon/server.py
```

## Model

Not bundled in git (12 MB). At first start `run.sh` resolves the model as:

1. `/share/bambu_ai_model/best.onnx` if present, else
2. download from the `model_url` add-on option to `/data/best.onnx`.

## First push: make the GHCR package public

`ghcr.io/leenc123/bambu-inference` defaults to private → sidecar pull gets
401 on user machines. After the first workflow run:
GitHub → avatar → *Your packages* → *bambu-inference* → *Package settings* →
*Change visibility* → *Public*. One-time step.

## Same image for the Docker sidecar

`service_manager.py` pulls `ghcr.io/leenc123/bambu-inference:latest`,
built from this directory's `Dockerfile` (+ staged `best.onnx` in CI).
Sidecar mounts `/config/bambu_ai_model` (staged automatically) at `/model`.
