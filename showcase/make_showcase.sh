#!/usr/bin/env bash
# Rebuild every showcase artifact from a clean clone.
#
# Tool requirements:
#   - uv            (Python env; Python 3.11+ is fetched by uv if missing)
#   - vhs >= 0.10   https://github.com/charmbracelet/vhs  (needs ttyd + ffmpeg + a Chromium)
#   - ttyd          https://github.com/tsl0922/ttyd
#   - ffmpeg / ffprobe
#   - optional, live bench only: NVIDIA_NIM_API_KEY (free tier) and LIVE=1
#
# Fixed seeds: the bench uses seeds 0,1,2 (pairs shuffle + provider seed); the
# demo replays a recorded trace, so the GIF/MP4/poster are deterministic.
#
#   bash showcase/make_showcase.sh          # replay assets + json from committed results
#   LIVE=1 bash showcase/make_showcase.sh   # also re-measure the bench live (~1,900 LLM calls)
set -euo pipefail
cd "$(dirname "$0")/.."

TRACE="${DEMO_TRACE:-fixtures/demo/03-hype-lottery.json}"
[ -f "$TRACE" ] || TRACE=fixtures/demo/01-transit-copilot.json
MODEL="${CONDORIUM_MODEL:-nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b}"

for tool in uv vhs ttyd ffmpeg ffprobe; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

[ -x .venv/bin/python ] || uv venv -q -p 3.11 .venv
uv pip install -q --python .venv/bin/python -e ".[dev,showcase]"
export PATH="$PWD/.venv/bin:$PATH"

pytest -q
panel demo >/dev/null   # both recorded runs replay offline

if [ "${LIVE:-0}" = "1" ]; then
  : "${NVIDIA_NIM_API_KEY:?LIVE=1 needs NVIDIA_NIM_API_KEY}"
  CONDORIUM_MODEL="$MODEL" CONDORIUM_MAX_CALLS=620 \
    panel bench --versus --n 3 --tone 2 --seeds 0,1,2 --workers 3 \
    --out showcase/results/versus_results.json
fi

python showcase/poster.py "$TRACE" showcase/results/versus_results.json showcase/poster.png
DEMO_TRACE="$TRACE" vhs showcase/demo.tape
python showcase/build_json.py "$TRACE"

# acceptance checks for the portfolio site
python - <<'PY'
import json, os, subprocess
from PIL import Image
assert Image.open("showcase/poster.png").size == (1280, 720)
gif = Image.open("showcase/demo.gif")
assert gif.size[0] <= 1280, gif.size
assert os.path.getsize("showcase/demo.gif") < 10 * 1024 * 1024
probe = lambda f, e: subprocess.check_output(["ffprobe", "-v", "error", *e, f], text=True).strip()
dur = float(probe("showcase/demo.mp4", ["-show_entries", "format=duration", "-of", "csv=p=0"]))
codec = probe("showcase/demo.mp4", ["-select_streams", "v:0", "-show_entries",
                                    "stream=codec_name", "-of", "csv=p=0"])
assert dur <= 40 and codec == "h264", (dur, codec)
json.load(open("showcase/showcase.json"))
print(f"showcase ok: demo {dur:.1f}s h264, gif {os.path.getsize('showcase/demo.gif')/1e6:.1f} MB")
PY
