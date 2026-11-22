# lab

repo for compose files

Run Compose operations through the lab CLI (for example, `python3 cli.py up`).
Each beaker's `.beaker` manifest stores its CLI metadata and the allowlist of
root `.env` keys loaded for Compose interpolation. A container receives only
variables explicitly listed in its Compose `environment` section.
