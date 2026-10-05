import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import secrets
from .backends import BleVehicle, SimulatedVehicle
from .server import RelayServer
from .wire import RelayClient
from .framing import vehicle_name


async def run(args):
    if args.command == "name":
        print(vehicle_name(args.vin))
        return
    if args.command == "scan":
        from bleak import BleakScanner
        target = vehicle_name(args.vin) if args.vin else args.name
        def found(device, advertisement):
            if target is None or advertisement.local_name == target:
                print(json.dumps({"name": advertisement.local_name, "address": device.address,
                                  "rssi": advertisement.rssi, "services": advertisement.service_uuids,
                                  "manufacturer_data_lengths": {str(k): len(v) for k, v in advertisement.manufacturer_data.items()}}), flush=True)
        async with BleakScanner(detection_callback=found):
            await asyncio.sleep(args.timeout)
        return
    if args.command == "token":
        path = Path(args.token_file)
        with path.open("x") as file:
            os.chmod(path, 0o600)
            file.write(secrets.token_hex(32) + "\n")
        print(f"Created {path}")
        return
    if args.command == "diagnose":
        async with BleVehicle(args.vin, args.timeout) as vehicle:
            print(json.dumps(vehicle.info(), indent=2))
            print("PASS: discovery, connection, service discovery, response subscription. No commands sent.")
        return
    token = Path(args.token_file).read_text().strip()
    if args.command == "serve":
        if args.backend == "ble" and not args.vin:
            raise ValueError("--vin is required for a physical vehicle")
        factory = (lambda: BleVehicle(args.vin)) if args.backend == "ble" else (lambda: SimulatedVehicle(args.delay_ms, args.jitter_ms))
        server = RelayServer(token, factory)
        port = await server.start(args.port)
        print(f"Listening on 127.0.0.1:{port} ({args.backend}); Ctrl-C to stop", flush=True)
        try:
            await asyncio.Event().wait()
        finally:
            await server.close()
    elif args.command == "probe":
        client = RelayClient("127.0.0.1", args.port, token)
        try:
            info = await client.connect()
            print(json.dumps(info))
            if info.get("backend") != "simulation":
                raise ValueError("echo probe refuses to send test payloads to a physical vehicle")
            for length in [1, 19, 20, 21, 255, 512, 1024]:
                data = bytes(i % 256 for i in range(length))
                await client.write(data)
                response = await asyncio.wait_for(client.read(), 5)
                if response != data:
                    raise RuntimeError(f"echo mismatch for {length} bytes")
            print("PASS: seven sizes, including 1024 bytes, echoed byte-for-byte")
        finally:
            await client.close()


def main():
    parser = argparse.ArgumentParser(description="Experimental phone key transport lab")
    sub = parser.add_subparsers(dest="command", required=True)
    name = sub.add_parser("name", help="Compute the vehicle Bluetooth name locally")
    name.add_argument("--vin", required=True)
    scan = sub.add_parser("scan", help="Observe advertisements; does not connect or send commands")
    target = scan.add_mutually_exclusive_group()
    target.add_argument("--vin")
    target.add_argument("--name")
    scan.add_argument("--timeout", type=float, default=15)
    token = sub.add_parser("token")
    token.add_argument("--token-file", default="lab.token")
    serve = sub.add_parser("serve")
    serve.add_argument("--backend", choices=["simulation", "ble"], default="simulation")
    serve.add_argument("--vin")
    serve.add_argument("--delay-ms", type=float, default=0)
    serve.add_argument("--jitter-ms", type=float, default=0)
    diagnose = sub.add_parser("diagnose")
    diagnose.add_argument("--vin", required=True)
    diagnose.add_argument("--timeout", type=float, default=20)
    probe = sub.add_parser("probe", help="Echo test; use ONLY against simulation")
    for command in [serve, probe]:
        command.add_argument("--port", type=int, default=8765)
        command.add_argument("--token-file", default="lab.token")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        parser.exit(1, f"Error: {error}\n")
