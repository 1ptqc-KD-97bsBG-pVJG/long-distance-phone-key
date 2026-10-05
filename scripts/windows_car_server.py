"""Run the car-side server in a Windows console and hold a temporary wake request."""
import argparse
import asyncio
import ctypes
import json
import logging
import os
from pathlib import Path

from phone_key_lab.backends import BleVehicle, SimulatedVehicle
from phone_key_lab.server import RelayServer

ROOT = Path(__file__).resolve().parent.parent


async def run(args):
    config = json.loads((ROOT / 'car-config.json').read_text(encoding='utf-8'))
    token = (ROOT / config['token_file']).read_text(encoding='utf-8').strip()
    factory = (lambda: SimulatedVehicle(40, 30)) if args.backend == 'simulation' else (lambda: BleVehicle(config['vin']))
    server = RelayServer(token, factory)
    pid_file = ROOT / 'relay.pid'
    port = await server.start(config['port'])
    pid_file.write_text(str(os.getpid()))
    print(f'Listening on 127.0.0.1:{port} ({args.backend}). Leave this window open; Ctrl-C stops the server.', flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await server.close()
        pid_file.unlink(missing_ok=True)


def main():
    if os.name != 'nt':
        raise SystemExit('This launcher is for Windows only.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['ble', 'simulation'], default='ble')
    args = parser.parse_args()
    os.chdir(ROOT)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
                        handlers=[logging.FileHandler(ROOT / 'relay.log', encoding='utf-8'), logging.StreamHandler()])
    power = ctypes.windll.kernel32.SetThreadExecutionState
    power.argtypes = [ctypes.c_uint32]
    power.restype = ctypes.c_uint32
    if not power(0x80000001):
        raise OSError('Windows could not establish a temporary system wake request.')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    finally:
        power(0x80000000)


if __name__ == '__main__':
    main()
