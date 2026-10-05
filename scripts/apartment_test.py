"""Run the real Mac peripheral against an echo backend, without a vehicle."""
import asyncio
import argparse
from pathlib import Path
import secrets
from phone_key_lab.backends import SimulatedVehicle, ObserveVehicle
from phone_key_lab.server import RelayServer

ROOT = Path(__file__).resolve().parent.parent


async def main(args):
    if args.discovery_only and not args.observe:
        raise SystemExit('--discovery-only requires --observe; no echo payloads are used')
    app = ROOT / "build/PhoneKeyProxy.app"
    if not app.exists():
        raise SystemExit("Build the Mac app first: .venv/bin/python scripts/build_mac.py")
    token_file = Path(args.token_file).resolve()
    token_file.parent.mkdir(exist_ok=True)
    token = secrets.token_hex(32)
    with token_file.open('x') as file:
        token_file.chmod(0o600)
        file.write(token)
    factory = ObserveVehicle if args.observe else lambda: SimulatedVehicle(40, 30)
    server = RelayServer(token, factory)
    port = await server.start()
    print("Opening Mac proxy. Allow Bluetooth access if macOS asks.", flush=True)
    if args.observe:
        print("Discovery-only observation: no authenticated vehicle replies are generated.", flush=True)
    else:
        print("On the Android test app, match the proxy name and tap Run echo test.", flush=True)
    process = None
    try:
        process = await asyncio.create_subprocess_exec("open", "-W", "-n", str(app), "--args",
            "--name", args.name, "--mode", args.mode, "--port", str(port),
            "--token-file", str(token_file), "--auto-start",
            *(["--discovery-only"] if args.discovery_only else []))
        await process.wait()
    finally:
        if process and process.returncode is None:
            process.terminate()
            await process.wait()
        await server.close()
        token_file.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", action="store_true", help="Accept messages without replying; for official app discovery only")
    parser.add_argument("--discovery-only", action="store_true", help="Apartment GATT diagnostic: keep advertising and reject payload writes; requires --observe")
    parser.add_argument("--token-file", default=str(ROOT / "artifacts/apartment.token"))
    parser.add_argument("--name", default="PKLab")
    parser.add_argument("--mode", choices=["both", "name-only", "service-only", "tesla-name"], default="both")
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
