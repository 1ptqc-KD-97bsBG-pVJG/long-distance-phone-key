from pathlib import Path
import plistlib
import os
import subprocess

root = Path(__file__).resolve().parent.parent
app = root / "build/PhoneKeyProxy.app"
contents = app / "Contents"
binary = contents / "MacOS/PhoneKeyProxy"
binary.parent.mkdir(parents=True, exist_ok=True)
with (contents / "Info.plist").open("wb") as file:
    plistlib.dump({"CFBundleIdentifier": "dev.phonekey.proxy", "CFBundleName": "PhoneKeyProxy",
                  "CFBundleExecutable": "PhoneKeyProxy", "CFBundlePackageType": "APPL",
                  "CFBundleVersion": "1", "NSBluetoothAlwaysUsageDescription": "Advertise the experimental phone key transport to your test Android phone.",
                  "NSBluetoothPeripheralUsageDescription": "Advertise the experimental phone key transport to your test Android phone.",
                  "NSHighResolutionCapable": True}, file)
subprocess.run(["swiftc", "-swift-version", "5", str(root / "mac/PhoneKeyProxy.swift"),
                "-o", str(binary), "-framework", "AppKit", "-framework", "CoreBluetooth", "-framework", "Network"], check=True)
identity = os.environ.get("PHONE_KEY_SIGNING_IDENTITY", "-")
signing = ["codesign", "--force", "--sign", identity]
if identity == "-":
    # Stable local development identity across builds; never distribute this signature.
    signing += ["--requirements", '=designated => identifier "dev.phonekey.proxy"']
subprocess.run([*signing, str(app)], check=True)
print(app)
