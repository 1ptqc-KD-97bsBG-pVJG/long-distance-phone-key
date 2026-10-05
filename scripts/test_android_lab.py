"""Automate our own Android test app on an explicitly selected lab device.

The caller supplies the device CLI session/config. No other AVD is opened or reset.
"""
import argparse
import asyncio
import os
from contextlib import suppress
from pathlib import Path
import re
import secrets
import uuid
from types import SimpleNamespace
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
from phone_key_lab.server import RelayServer
from phone_key_lab.backends import SimulatedVehicle
from phone_key_lab.virtual import run as virtual_proxy

ROOT = Path(__file__).resolve().parent.parent


async def command(*args):
    process = await asyncio.create_subprocess_exec(*map(str, args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    output, errors = await process.communicate()
    text = output.decode(errors="replace")
    if process.returncode:
        raise RuntimeError(text + errors.decode(errors="replace"))
    return text


async def main(args):
    artifact = ROOT / "artifacts"
    artifact.mkdir(exist_ok=True)
    adb = Path(args.sdk) / "platform-tools/adb"
    # Require the specifically created AVD; refuse shared emulator ids by mistake.
    avd = (await command(adb, "-s", args.serial, "emu", "avd", "name")).splitlines()[0]
    if avd != "Phone_Key_Lab_API_35":
        raise RuntimeError(f"Refusing to test on {avd}; select Phone_Key_Lab_API_35")
    cli = [args.agent, "--platform", "android", "--serial", args.serial,
           "--config", args.config, "--session", args.session]
    # Operation comes before target flags in agent-device.
    async def device(operation, *params):
        return await command(cli[0], operation, *params, *cli[1:])
    await device("install", "dev.phonekey.lab", ROOT / "build/android/phone-key-lab.apk")
    for permission in ["BLUETOOTH_SCAN", "BLUETOOTH_CONNECT"]:
        await command(adb, "-s", args.serial, "shell", "pm", "grant", "dev.phonekey.lab", "android.permission." + permission)
    await device("open", "dev.phonekey.lab")
    token_path = artifact / "android-lab.token"
    token = secrets.token_hex(32)
    token_path.write_text(token)
    token_path.chmod(0o600)
    report = []
    try:
        for delay, jitter in [(0, 0), (40, 30), (200, 100)]:
            server = RelayServer(token, lambda: SimulatedVehicle(delay, jitter))
            port = await server.start()
            near = asyncio.create_task(virtual_proxy(SimpleNamespace(
                port=port, token_file=str(token_path), name="PKLab",
                transport="android-netsim:name=phone-key-lab-proxy")))
            try:
                # Allow virtual controller setup. Fail early if setup failed.
                await asyncio.sleep(2)
                if near.done():
                    near.result()
                    raise RuntimeError("proxy stopped before the phone connected")
                marker = "LAB_RUN=" + uuid.uuid4().hex
                await command(adb, "-s", args.serial, "shell", "log", "-p", "i", "-t", "PhoneKeyLab", marker)
                snapshot = await device("snapshot", "-i")
                field = re.search(r'(@e\d+) \[text-field\]', snapshot)
                button = re.search(r'(@e\d+) \[button\] "RUN ECHO TEST"', snapshot)
                if not field or not button:
                    raise RuntimeError("test app controls missing: " + snapshot)
                await device("fill", field.group(1), "PKLab")
                snapshot = await device("snapshot", "-i")
                button = re.search(r'(@e\d+) \[button\] "RUN ECHO TEST"', snapshot)
                if not button:
                    raise RuntimeError("test button missing after filling name: " + snapshot)
                await device("click", button.group(1))
                deadline = asyncio.get_running_loop().time() + 90
                while asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(1)
                    all_logs = await command(adb, "-s", args.serial, "logcat", "-d", "-s", "PhoneKeyLab:I", "*:S")
                    if marker not in all_logs:
                        continue
                    logs = all_logs.split(marker, 1)[1]
                    if "FAIL:" in logs:
                        raise RuntimeError(logs)
                    if "PASS: ALL 21 ECHO EXCHANGES" in logs:
                        break
                else:
                    raise RuntimeError("Android lab timed out")
                (artifact / f"android-{delay}ms.log").write_text(logs)
                report.append(f"PASS: 21 exchanges, delay={delay}ms, jitter=0..{jitter}ms")
                print(report[-1], flush=True)
                await asyncio.wait_for(near, 10)
            finally:
                near.cancel()
                with suppress(asyncio.CancelledError):
                    await near
                await server.close()
        await device("screenshot", artifact / "android-lab.png")
        (artifact / "android-summary.txt").write_text("\n".join(report) + "\n")
    finally:
        token_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--agent", default=str(Path.home() / ".t3/userdata/device/bin/agent-device"))
    parser.add_argument("--sdk", default=str(Path.home() / "Library/Android/sdk"))
    asyncio.run(main(parser.parse_args()))
