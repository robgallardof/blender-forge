"""Install the bridge extension into Blender and create the shared token.

    blender-forge-install            # build, install and enable the extension (user repo)
    blender-forge-install --check    # report what is installed, change nothing
    blender-forge-install --remove   # uninstall the extension (the token file stays)

Uses Blender's own extension CLI (`blender -c extension ...`), so Blender stays in charge of
where extensions live and which ones are enabled.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .addon import protocol
from .client import ADDON_DIR, Client, find_blender

EXTENSION_ID = "blender_forge_bridge"
REPO = "user_default"


def run(exe, *args):
    proc = subprocess.run([str(exe), "--factory-startup", "-c", "extension", *args],
                          capture_output=True, text=True, timeout=300)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def build(exe, out_dir):
    src = Path(out_dir) / "src"
    shutil.copytree(ADDON_DIR, src, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    code, output = run(exe, "build", "--source-dir", str(src), "--output-dir", str(out_dir))
    zips = sorted(Path(out_dir).glob(f"{EXTENSION_ID}-*.zip"))
    if code != 0 or not zips:
        raise SystemExit(f"extension build failed:\n{output}")
    return zips[-1]


def installed(exe):
    code, output = run(exe, "list")
    return EXTENSION_ID in output, output


def main(argv=None):
    parser = argparse.ArgumentParser(prog="blender-forge-install", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report only")
    parser.add_argument("--remove", action="store_true", help="uninstall the extension")
    parser.add_argument("--allow-python", action="store_true",
                        help="let agents run arbitrary Python in Blender (off by default)")
    args = parser.parse_args(argv)

    exe = find_blender()
    if exe is None:
        print("Blender not found. Install it or set BLENDER_FORGE_BLENDER.", file=sys.stderr)
        return 2
    present, _ = installed(exe)
    if args.check:
        config = protocol.config_path()
        pong = Client().reachable() if config.exists() else None
        print(json.dumps({"blender": str(exe), "extension_installed": present, "config": str(config),
                          "config_exists": config.exists(), "bridge_reachable": bool(pong)}, indent=2))
        return 0
    if args.remove:
        if not present:
            print("extension not installed; nothing to do")
            return 0
        code, output = run(exe, "remove", f"{REPO}.{EXTENSION_ID}")
        print(output or "removed")
        return code
    config = protocol.load_config(create=True)
    if args.allow_python != bool(config.get("allow_python")):
        config["allow_python"] = args.allow_python
        protocol.config_path().write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="blender-forge-build-") as tmp:
        package = build(exe, tmp)
        code, output = run(exe, "install-file", "--repo", REPO, "--enable", str(package))
    if code != 0:
        print(output, file=sys.stderr)
        return code
    print(f"installed {package.name} into Blender ({exe})")
    print(f"token: {protocol.config_path()} (port {config['port']}, python {'on' if config.get('allow_python') else 'off'})")
    print("Open Blender: the bridge starts with it. Or let the agent call start_headless.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
