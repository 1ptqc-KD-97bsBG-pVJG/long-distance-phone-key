# Long-distance phone key lab

An experimental Bluetooth **application-layer proxy** for testing whether an
authorized Android Tesla app can enroll its own phone key through two laptops.
It forwards application messages rather than Bluetooth radio packets. Testing
confirmed re-enrollment on the local test vehicle using two Macs and first-time
enrollment on the remote test vehicle using a Mac and Windows laptop over
Tailscale/SSH. The user confirmed both new entries on the vehicles’ touchscreen
key lists. Direct phone use with the proxy stopped was also confirmed on the
local test vehicle; direct use on the remote test vehicle remains pending until
the enrolled phone is physically beside that vehicle.

Before publishing a fork or release, follow the
[public-release checklist](docs/releasing.md). Keep local session artifacts and
private vehicle configuration out of Git.

The phone-facing Mac publishes the vehicle's documented GATT interface. It
forwards complete opaque messages over a loopback TCP connection to a car-side
client. The car-side client frames and fragments those messages for its actual
Bluetooth connection. Between laptops, the TCP connection must go through SSH.
Neither endpoint needs Tesla account credentials or phone key private keys.

## Current evidence

- With the browser endpoint added, all 29 Python tests pass. Android Chrome on
  a fresh API 35 emulator and Safari on an isolated iPhone 16 / iOS 26.4.1
  simulator completed invitation/approval, seven exact simulated round trips
  through the loopback TCP/WebSocket bridge, and disconnect cleanup. JavaScript fixture
  checks cover 20-byte GATT writes, fragmented indications, and cleanup. Real
  browser-to-vehicle BLE and Bluefy remain unverified.
- Physical Android Chrome on the spare Pixel 6 Pro completed two apartment GATT
  diagnostics against the Mac peripheral: name-only advertising and combined
  name/service advertising. Both passed chooser discovery, host approval, real
  service/characteristic discovery, response subscription, and browser disconnect.
  The page used USB forwarding to localhost; no payloads or vehicle commands were
  sent. iPhone Bluefy discovery/connection remains unverified.
- The dedicated Android emulator passed 63 byte-for-byte exchanges across three
  delay scenarios, including messages up to 1024 bytes.
- A USB-connected Pixel 6 Pro passed 63 physical Bluetooth echo exchanges through
  the Mac proxy: short-name/default MTU, full-name/name-only, and larger MTU
  (517 negotiated, 512-byte notification chunks).
- The spare phone's official Tesla app has authorized access to the local test vehicle and showed
  phone key setup as incomplete. In apartment-only observation mode, it discovered
  the Mac using `tesla-name`, subscribed, and sent 49- and 134-byte messages into
  the relay. No vehicle replies were fabricated and no key was enrolled.
- The local test vehicle passed real vehicle connection/service discovery/response subscription
  through the car-side MacBook. MTU was 247 and write size 244.
- With the spare Android and proxy Mac in the apartment and the second MacBook
  at the local test vehicle, the official app reported that Pixel 6 Pro was set up as a key.
  Bidirectional messages crossed the Tailscale/SSH relay. The proxy was stopped
  after setup finished. The user confirmed the new Pixel 6 Pro entry in the local test vehicle’s
  touchscreen key list and successful direct phone operation beside the car.
- The user subsequently noted that this phone had been enrolled on the local test vehicle before
  and was removed before the test. This establishes working re-enrollment through
  the relay, but does not establish first-ever enrollment of a phone/vehicle pair.
- The Windows 11 Home car-side laptop passed the original transport tests, native Bluetooth scanning
  over SSH (38 devices seen), and seven byte-for-byte echo exchanges through the
  actual Tailscale/SSH tunnel. It then connected to the remote test vehicle’s real Bluetooth service
  and subscribed for responses, with MTU 247 and write size 244.
- The Pixel 10 Pro XL’s official app progressed from “Set Up”
  through “Finishing up” and removed the setup card while messages crossed the
  Mac-to-Windows relay. The user confirmed that the remote test vehicle’s touchscreen listed the
  new Pixel 10 Pro XL key. The phone had never been enrolled on the remote test vehicle before.
  The Mac proxy was stopped and the Windows log confirmed the Bluetooth session
  ended. The Windows relay was then stopped. This confirms first-time remote
  enrollment; direct entry/driving with this phone remains untested.

The simulator is an echo fixture using Tesla's transport framing. It does not
implement Tesla authentication, proximity checks, or key enrollment. Never run
the echo test app directly against a Tesla.

## Set up

[Browser endpoint setup](docs/browser-endpoint.md). Android Chrome on a dedicated
For the new self-hosted car-side website, see emulator and Safari on an iOS
simulator passed the complete simulated bridge; physical browser BLE and iPhone
Bluefy still require hardware verification. The tested laptop endpoints below
remain available.

[next vehicle-session checklist](docs/next-car-test.md). Browser connection
The helper website presents four steps with icons, current-operation indicators,
elapsed waiting time, and one action at a time. Detailed help is collapsed. The
host website, Mac proxy, and Android lab app also show activity states. For a
visit testing both Android Chrome and iPhone Bluefy, follow the progress is
separate from successful key enrollment.

Python 3.11 or later:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[lab]'
.venv/bin/pytest -q
.venv/bin/python scripts/build_android.py
.venv/bin/python scripts/build_mac.py
```

The small Android build uses the locally installed API 35 SDK/build tools 35.0.0
and JDK 17; override `ANDROID_SDK_ROOT` and `PHONE_KEY_JDK` if necessary. The
Mac build requires Apple's Swift compiler and frameworks. Build outputs:

- `build/PhoneKeyProxy.app`
- `build/android/phone-key-lab.apk`

On a Windows car-side laptop, only the base package is needed; the emulator and
Mac build are not required:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Automated car-free tests

The suite exercises randomized BLE chunk boundaries/coalesced messages,
oversized or stale fragments, network delay/jitter, authentication rejection,
single-session enforcement, disconnects with pending responses, fresh sessions,
and mocked native car-side Bluetooth operations.

For the real Android stack, use **only this project's dedicated AVD**:

```sh
.venv/bin/python scripts/create_emulator.py
```

This creates `Phone_Key_Lab_API_35` with new userdata. It does not copy or reset
another emulator. If it already exists, reuse it instead of running creation
again. Open it using T3's device tools. If T3 cannot start it, a local fallback
is:

```sh
~/Library/Android/sdk/emulator/emulator \
  -avd Phone_Key_Lab_API_35 -port 5560 \
  -no-window -no-snapshot -no-audio -gpu swiftshader
```

Choose an unused emulator port; never shut down a device owned by another task.
Use the device config/session arguments from T3 or a distinct device CLI session
if T3's Device panel cannot attach. Then:

```sh
.venv/bin/python scripts/test_android_lab.py \
  --serial emulator-5560 \
  --config /absolute/path/to/device-host-config.json \
  --session your-project-device-session
```

The runner refuses to use an AVD other than `Phone_Key_Lab_API_35`. It installs
our test app, starts a fresh relay and virtual GATT peripheral for each
scenario, drives Android through the device CLI, and checks logs for 21
successful exchanges per scenario. Scenarios are 0 ms, 40–70 ms, and 200–300 ms
of simulated backend delay per exchange. These delays exercise the relay; they
are not measurements of the Tesla app's pairing timeouts. Logs and a screenshot
go to `artifacts/`.

## Apartment test: physical Android, no car

This hardware gate has passed on the connected spare Pixel. Connect a spare
Android over USB, enable USB debugging, and accept its computer authorization
prompt. Install the APK using the device CLI (or sideload it). Launch **Phone
Key Lab** and allow Nearby Devices access. Android 11 or earlier also needs
location permission/services for BLE scanning.

On the Mac:

```sh
.venv/bin/python scripts/apartment_test.py
```

This starts the echo backend and opens the Mac app configured as `PKLab`. Allow
the Mac app's Bluetooth permission if prompted. On Android, leave the target as
`PKLab` and tap **Run echo test**. Expected outcome: **ALL 21 ECHO EXCHANGES**.
Close the Mac app to stop the backend. Restart the Mac proxy for another phone
session. Keep the Mac awake during the test.

If discovery fails, inspect the Mac's status log. The app provides `both`,
`name-only`, `service-only`, and `tesla-name` advertising modes. The test app
scans by exact advertised name and then checks the GATT service, so `name-only`
is testable; `service-only` deliberately has no name and needs a BLE scanner
instead.

Apple limits the advertisement size. A full 18-character Tesla name plus the
128-bit GATT UUID was not discoverable by exact name in the physical test; name-
only did pass our echo test. The official app also checks service identifiers,
so name-only did not satisfy its discovery requirements.

`tesla-name` advertises the full vehicle name alongside the compact advertising
UUID `0x1122`. The published GATT service remains `00000211-...`. This
distinction was identified from the installed official Android app and confirmed
by a real connection and outbound messages. It is an app-version-dependent
observation, not an enrollment guarantee.

To repeat official-app discovery without the car, compute the name locally and
run an observation backend:

```sh
.venv/bin/phone-key-lab name --vin YOUR_17_CHARACTER_VIN
.venv/bin/python scripts/apartment_test.py --observe \
  --name YOUR_COMPUTED_BLUETOOTH_NAME --mode tesla-name
```

Use **Set Up Phone Key** in the official app. The Mac should log **Phone
subscribed** and **Phone → vehicle** message sizes. It intentionally sends no
replies, so the app will eventually report a setup failure. Close and restart
the proxy before another attempt. Do not use the echo backend with the official
app.

The Android test app also provides **Run with larger MTU**. Android 14+ can
request 517 bytes even when the app asks for 247. Both the 23-byte and 517-byte
MTU paths have passed physical tests.

### Mac Bluetooth permission across builds

The local build uses an explicit stable designated requirement for its ad hoc
signature. The first build with this identity may need Bluetooth permission; A
subsequent rebuild with a changed binary retained authorization in the physical
test. This is only a local development signature. Set
`PHONE_KEY_SIGNING_IDENTITY` to a proper code-signing identity to use that
instead. No certificates or keychain entries are created by the build script.

## First useful near-side car test

### A. Short diagnostic session

Bring one laptop running this project within Bluetooth range of your awake Model
3. Keep a working physical key available. You do not need to enroll or remove
any keys for this diagnostic.

```sh
.venv/bin/phone-key-lab scan --vin YOUR_17_CHARACTER_VIN --timeout 15
.venv/bin/phone-key-lab diagnose --vin YOUR_17_CHARACTER_VIN
```

The first command observes advertisements. The second connects, discovers the
documented service/characteristics, subscribes to the response characteristic,
prints properties/MTU, then disconnects. It sends no vehicle-control commands.
Successful subscription does not itself prove the vehicle sends responses or
accepts enrollment. macOS may require Bluetooth permission for the terminal
hosting the Python process.

If no connectable vehicle is found, wake the car and temporarily move other
connected phone keys out of range or disable their Bluetooth. Do not delete your
existing keys. Save the output for deciding whether to attempt stage B.

### macOS permissions when controlling a car-side laptop over SSH

A reachable SSH service does not guarantee Bluetooth authorization. On the
second Mac tested here, Bleak launched directly over SSH was denied by macOS.
Launch the car-side scan/server from a local Terminal window on that Mac and
approve Terminal's Bluetooth access if prompted. Leave the server running in
that window; use SSH for tunneling and reading logs. Verify an apartment BLE
scan before moving the laptop to the car. `caffeinate -i` can keep the laptop
awake during the session while its lid is open.

### B. Local relay enrollment experiment

After the apartment test and diagnostic pass, use two laptops:

```text
Spare Android + Mac in apartment
               │
          SSH tunnel
               │
     Car-side laptop + local Tesla
```

The Android phone **must be outside direct Bluetooth range of the Tesla**;
otherwise a successful pairing could bypass the proxy. Use a spare phone with
authorized access to your local vehicle in the official Tesla app. Keep your
primary phone key intact. Only the official app initiates enrollment, and any
vehicle-side authorization remains a manual action.

On the car-side laptop, create a token once:

```sh
.venv/bin/phone-key-lab token --token-file car.token
.venv/bin/phone-key-lab serve --backend ble --vin YOUR_17_CHARACTER_VIN \
  --port 18765 --token-file car.token
```

Windows equivalents use `.\.venv\Scripts\phone-key-lab.exe`. Securely copy the
same token file to the apartment Mac. The server binds only to loopback and
accepts one phone session; it connects to the car when the proxy authenticates.

If SSH access to the car-side laptop is already configured, on the apartment
Mac:

```sh
ssh -N -L 18765:127.0.0.1:18765 your-user@car-side-laptop
.venv/bin/phone-key-lab name --vin YOUR_17_CHARACTER_VIN
open build/PhoneKeyProxy.app
```

In the Mac app, enter the computed name, port `18765`, and the absolute path to
the copied token. Select `tesla-name`. Click **Start proxy**. Wait for
**ADVERTISING**, then initiate **Set Up Phone Key** in the official Tesla app on
the spare Android. Follow any prompts at the car.

SSH direction can be reversed if the car-side laptop can SSH into the apartment
Mac: run `ssh -N -R 18765:127.0.0.1:18765 your-user@apartment-mac` on the car-
side laptop. Do not expose the relay TCP port directly on Wi-Fi or the internet.

For remote iteration, the car-side laptop needs power, an internet connection,
and Bluetooth proximity to the vehicle. The car needs to remain reachable;
leaving the doors unlocked alone does not establish that it will stay awake.

### What to record

- Whether the car diagnostic discovers the expected interface.
- Which Mac advertising mode the official app discovers.
- Whether the Mac logs **Phone subscribed** and message sizes in both directions.
- The app's exact progress/error and any vehicle prompt.
- Whether the spare phone appears in the vehicle's key list.

The real car sent unsolicited status notifications immediately after connection.
The Mac proxy discards these until a phone subscribes, then forwards messages
normally. It does not replay the discarded status into a new phone session.

The proxy logs lengths/status, not opaque message contents, tokens, or key
material. It stops on disconnect, malformed framing, or queue overflow and
requires a fresh session rather than attempting to continue stale enrollment.

After enrollment, stop the relay and verify the vehicle’s key list. When the
enrolled phone is physically beside the vehicle, check direct entry and driving
with both relays stopped. That final check has passed on the local test vehicle
and remains pending on the remote test vehicle.

## Sources and limits

- [Tesla's official BLE connector](https://github.com/teslamotors/vehicle-command/blob/main/pkg/connector/ble/ble.go): VIN-derived name, service UUIDs, two-byte message length, fragmentation, and reference message-size limit.
- [Tesla phone key setup](https://www.tesla.com/ownersmanual/model3/en_us/GUID-E004FAB7-1C71-448F-9492-CACF301304D2.html): supported local enrollment and key behavior.
- [Apple code-signing requirements](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements): why the default ad hoc identity changes with each binary.
- [Apple peripheral advertising](https://developer.apple.com/documentation/corebluetooth/cbperipheralmanager/startadvertising(_:)): supported fields and advertising limits.
- [Google Bumble Android integration](https://google.github.io/bumble/platforms/android.html): virtual GATT devices through Netsim.
- [Bleak client API](https://bleak.readthedocs.io/en/latest/api/client.html): native Bluetooth connections, writes, notifications/indications, and packet-size limits.

The official Android app may use behavior not present in the published Tesla
client. The proxy does not forward link-layer identity, Bluetooth bonding, RSSI,
or UWB ranging. A failure at one of those boundaries could require a different
approach; a successful echo test cannot rule it out.

## Prepared Windows car-side launcher

`scripts/windows_car_server.py` reads local `car-config.json` (VIN, port,
`token_file`), binds the relay to loopback, and holds a temporary Windows system
wake request while it runs. It releases the wake request on normal exit; it does
not change the persistent power plan. Keep the laptop lid open. Create a local,
ignored `car-config.json` at the repository root:

```json
{
  "vin": "YOUR_17_CHARACTER_VIN",
  "port": 18765,
  "token_file": "car.token"
}
```

After generating the token as described above, run this command in an ordinary
local PowerShell window:

```powershell
.\.venv\Scripts\python.exe scripts\windows_car_server.py
```

Keep that console open; Ctrl-C stops the server. This avoids depending on a
continuous SSH session during network changes. `relay.log`, `relay.pid`, and
`car-config.json` are local files excluded from Git.
