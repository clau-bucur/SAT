#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install pytest-homeassistant-custom-component

version=$(python -c "from homeassistant.const import __version__; print(__version__)")
package=$(python -c "from importlib.metadata import distribution; print(distribution('homeassistant').locate_file('homeassistant'))")

aioesphomeapi=$(python -c "import json, sys; from pathlib import Path; print(next(item for item in json.loads(Path(sys.argv[1]).read_text())['requirements'] if item.startswith('aioesphomeapi')))" "${package}/components/esphome/manifest.json")

python -m pip install -c "${package}/package_constraints.txt" -r requirements_test_latest.txt "${aioesphomeapi}"

echo "Testing against Home Assistant ${version} with ${aioesphomeapi}"
