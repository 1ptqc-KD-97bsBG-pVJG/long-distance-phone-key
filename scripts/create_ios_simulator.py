"""Create an isolated iOS web-test device; never modify another simulator."""
import argparse
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--name', default='Phone_Key_Web_iOS')
parser.add_argument('--device', default='iPhone 16')
args = parser.parse_args()

def simctl(*parts):
    return subprocess.check_output(['xcrun', 'simctl', *parts], text=True).strip()

try:
    devices = json.loads(simctl('list', 'devices', '--json'))['devices']
    if any(d['name'] == args.name for group in devices.values() for d in group):
        raise SystemExit('That simulator name already exists. Choose a fresh --name; no existing device was changed.')
    runtimes = [r for r in json.loads(simctl('list', 'runtimes', '--json'))['runtimes']
                if r.get('isAvailable') and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
    if not runtimes:
        raise SystemExit('Install an iOS runtime first: xcodebuild -downloadPlatform iOS')
    runtime = max(runtimes, key=lambda r: tuple(int(v) for v in r['version'].split('.')))
    types = json.loads(simctl('list', 'devicetypes', '--json'))['devicetypes']
    device_type = next((d for d in types if d['name'] == args.device), None)
    if not device_type:
        raise SystemExit('Requested iPhone device type is not available in this Xcode installation.')
    device_id = simctl('create', args.name, device_type['identifier'], runtime['identifier'])
    evidence = Path(__file__).resolve().parent.parent / 'artifacts/ios-simulator.json'
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(json.dumps({'name': args.name, 'id': device_id, 'runtime': runtime['identifier']}, indent=2) + '\n')
    print(device_id)
except subprocess.CalledProcessError:
    raise SystemExit('simctl failed. Complete Xcode license/first launch and check xcode-select first.')
