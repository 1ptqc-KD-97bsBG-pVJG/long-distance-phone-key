"""Create a fresh AVD without copying or modifying another agent's userdata."""
from pathlib import Path
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--name', default='Phone_Key_Lab_API_35')
name = parser.parse_args().name
if not name.replace('_', '').isalnum():
    raise SystemExit('Use only letters, digits and underscores in the AVD name')
sdk = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "Library/Android/sdk"))
root = Path.home() / ".android/avd"
avd = root / f"{name}.avd"
image = sdk / "system-images/android-35/google_apis/arm64-v8a"
if not image.exists():
    raise SystemExit(f"Install the API 35 arm64 Google APIs image first: {image}")
avd.mkdir(parents=True, exist_ok=False)
(root / f"{name}.ini").write_text(f"avd.ini.encoding=UTF-8\npath={avd}\npath.rel=avd/{name}.avd\ntarget=android-35\n")
(avd / "config.ini").write_text(f"""avd.ini.encoding=UTF-8
AvdId={name}
avd.ini.displayname=Phone Key Lab API 35
abi.type=arm64-v8a
hw.cpu.arch=arm64
hw.cpu.ncore=2
hw.ramSize=1536
hw.lcd.width=1080
hw.lcd.height=1920
hw.lcd.density=420
hw.keyboard=yes
hw.gpu.enabled=yes
hw.gpu.mode=auto
hw.audioInput=no
hw.audioOutput=no
hw.camera.back=none
hw.camera.front=none
hw.gps=yes
hw.battery=yes
hw.sdCard=no
disk.dataPartition.size=4G
image.sysdir.1={image}/
tag.id=google_apis
tag.display=Google APIs
target=android-35
fastboot.forceColdBoot=yes
""")
print(f"Created dedicated AVD: {name}")
