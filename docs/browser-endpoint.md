# Self-hosted browser endpoint

The near-side Mac runs the web server, a loopback TCP bridge, and the existing
Mac Bluetooth proxy. The helper beside the car opens a website in Android
Chrome or, provisionally, iPhone Bluefy. No project-hosted server is used.

Current verification: Android Chrome on a dedicated API 35 emulator and Safari
on a dedicated iPhone 16 / iOS 26.4.1 simulator passed host approval, all seven
simulated round trips (1–1024 bytes), and session termination on probe disconnect.
Safari also displayed the unsupported-Bluetooth guidance for non-simulation
invitations. Python socket integration and JavaScript GATT fixture tests pass.
Real browser-to-vehicle BLE and iPhone Bluefy have **not** been verified. These
simulator checks establish browser session behavior, not physical Bluetooth
compatibility. The existing laptop endpoints remain the vehicle-tested fallback.

Physical Chrome on a USB-connected Pixel 6 Pro also passed Mac test-peripheral
discovery, real GATT connection, service/characteristic discovery, response
subscription, and disconnect in both name-only and combined name/service
advertising modes. That diagnostic used USB forwarding for the page and wireless
Bluetooth for GATT; it sent no payloads and did not involve a car.

## Install

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[web]'
```

To build the phone-facing Mac app, follow the main README. It remains necessary
when enrolling a remote phone; browser APIs here implement only the car side.

## Apartment test

```sh
.venv/bin/phone-key-web --simulation
```

Terminal prints a private host-control link and a partner invitation. Open the
host link on the Mac and the invitation in the test browser. Local desktop
browsers can use localhost directly. On a dedicated Android emulator:

```sh
adb -s YOUR_DEDICATED_EMULATOR reverse tcp:8787 tcp:8787
```

Then open the invitation in that emulator's Chrome. Do not use this command on
another agent's emulator. The default local invitation uses `localhost`, which
is a secure context for browser API purposes. An Android emulator accessing
`http://10.0.2.2` is not equivalent to an HTTPS origin for physical BLE testing.
For an actual phone in the apartment, use the HTTPS/Tailscale steps below.

For an isolated iOS simulator, first install Xcode and an iOS runtime, then run:

```sh
xcodebuild -downloadPlatform iOS
.venv/bin/python scripts/create_ios_simulator.py
```

The script prints the new device UUID and refuses to reuse an existing name.
Open that device in T3’s Device panel and use its returned config/session flags
for every `agent-device` command. Safari in the simulator can open the local
invitation at `http://localhost:8787` without port forwarding. Simulation mode
works in Safari; it does not require Web Bluetooth. Never alter another task’s
simulator.

Tap **Start test**. Read the displayed code, approve the same code on
the host page, and wait for the connected state. Then, on the Mac:

```sh
.venv/bin/phone-key-lab probe --port 18765 --token-file artifacts/web-session.token
```

The browser simulates the vehicle and exercises framing and 20-byte chunking.
The probe refuses a physical backend. When it disconnects, the one-shot session
ends. Start a new server to repeat. Never use the official Tesla app with this
echo fixture; it does not implement authentication or key enrollment.

For an apartment-only **physical Bluetooth discovery/subscription** check, use
`--test-peripheral SBluefy` instead of `--simulation` or `--vin`. In a separate
Terminal, start a Mac diagnostic peripheral:

```sh
.venv/bin/python scripts/apartment_test.py --observe --discovery-only \
  --name SBluefy --mode both
```

This explicit Mac diagnostic mode keeps advertising after subscriptions and
rejects all payload writes. It is separate from the normal single-client relay
and cannot perform an echo exchange or enrollment. Close its Mac app after the
check. The Android test app also has a fifteen-second **Scan only — no connection**
button for observing the named advertisement without connecting or writing.
The web endpoint treats this as physical BLE, so the echo probe still refuses it.
Do not start the phone-facing enrollment proxy or use the official Tesla app for
this diagnostic. The browser shows each connection/discovery/subscription step
and times out an unfinished step after fifteen seconds. The normal single-client
Mac proxy stops advertising after a subscription; a nearby automatic client can
therefore make it disappear before Bluefy's picker sees it. Renaming alone does
not guarantee that a cached client will stop reconnecting.

## Private access through Tailscale Serve

1. Install Tailscale on the Mac. Enable HTTPS through the Serve setup flow.
2. The partner installs Tailscale and signs into their own account.
3. Share the **near-side Mac** with the partner. Allow access to its HTTPS port
   through the relevant tailnet access policy; no SSH access is needed.
4. Run the local server with the Mac's full HTTPS origin:

```sh
.venv/bin/phone-key-web --vin YOUR_VIN --public-url https://YOUR_MAC.YOUR_TAILNET.ts.net
```

5. In a separate Terminal, proxy the web server through Serve:

```sh
tailscale serve --https=443 http://127.0.0.1:8787
```

Check existing Serve configuration before using a port already in use. The
application does not alter Tailscale configuration or expose anything publicly.
This setup uses HTTP reverse proxying, including a same-origin WebSocket route;
forwarding the old raw TCP port to a website does not implement this protocol.

Send only the **partner invitation**, never the host-control link or local relay
token. The invitation contains its secret in the URL fragment, not the HTTP
path/query. Both pages remove the fragment after reading it; reopening requires
the original link. Access logs are disabled. Session secrets are not stored in
browser localStorage or cookies. Treat invitation links as temporary secrets.

## Helper beside the vehicle

- Android: open the invitation in Chrome.
- iPhone: install Bluefy and open the original invitation there. Safari is not
  supported. Bluefy is a proposed compatibility target, not yet confirmed.
- Tap **Connect to vehicle**, select the intended Tesla, and read the code to the
  host. The website verifies the chosen Bluetooth name against the session.
- Keep the browser visible and phone awake. The page requests a screen wake lock
  when supported, but this is not a guarantee of background operation.
- After setup, check **Controls → Locks** for the new phone key. Leave existing
  keys unchanged, then end the session.

No Tesla account login, USB debugging, Python, shell commands, or SSH server is
required on the helper's phone.

## Near-side enrollment

Approve the matching code in the private host page. Wait for **Vehicle connected**
before starting the Mac proxy with the arguments printed in Terminal:

```sh
open -n build/PhoneKeyProxy.app --args --name VEHICLE_BLE_NAME \
  --mode tesla-name --port 18765 --token-file "$PWD/artifacts/web-session.token" --auto-start
```

Use the printed name, port, and token-file path rather than the placeholders.
Then use **Set Up** in the authorized phone's official Tesla app. The phone may
be operated by its owner; USB debugging is not part of the forwarding path.
Stop the session after key-list confirmation. Test normal entry and driving
with the phone directly beside the car and both endpoints stopped when feasible.

The Mac currently has a 45-second backend-ready timeout, which is why it should
be started after browser readiness. Browser sessions expire after ten minutes
by default (`--minutes`, maximum thirty). Invitations are single-use, including
when a helper disconnects before approval. Restart the server for a new session.

Ctrl-C stops the server and removes its private token file. Stop the Serve
process/configuration created for this session too; preserve unrelated Serve
configuration. Do not leave forwarding running after enrollment.

## Architecture and limits

`web_server.py` implements an authenticated WebSocket endpoint and a
`BrowserVehicle` backend for the existing loopback `RelayServer`. The native Mac
proxy continues to speak the existing JSON-lines protocol. In the browser,
`transport.js` handles Tesla framing, conservative 20-byte GATT writes (there is
no portable browser MTU API), serialized operations, notification assembly,
fragment expiry, and disconnect cleanup.

There are separate random secrets for the invitation, host controls, and local
Mac proxy. The host must approve a connection before vehicle connection or
forwarding. Authentication, origin checks, bounded messages/queues, expiry, and
one-session lifecycle are enforced by the server, independently of page UI.
The code is opaque forwarding; these controls do **not** cryptographically limit
an approved session to enrollment rather than other vehicle messages.

The server binds to loopback and expects Tailscale Serve to provide remote HTTPS
and access controls. No public Funnel mode, rendezvous service, or persistent
cloud deployment is configured. The first physical-browser checks should be
connection/service discovery/subscription only before attempting enrollment.

## Developer checks

```sh
.venv/bin/pip install -e '.[lab,web]'
.venv/bin/pytest -q
node scripts/test_web_transport.mjs
```

The JavaScript fixture checks exact byte framing, invalid/stale fragments,
minimum-MTU chunks, notification assembly, device-name mismatch, and disconnect.
The socket tests cover authorization, origin checks, one-use invitations,
approval, seven message sizes, and termination of both bridge directions.
Neither set of tests proves actual browser Bluetooth compatibility.
