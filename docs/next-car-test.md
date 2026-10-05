# Next local vehicle session: Android and iPhone helpers

## Prepared roles

- **Enrolled phone:** the USB-connected spare Android stays beside the near-side
  Mac, outside direct Bluetooth range of the vehicle. The agent operates its
  official Tesla app; it remains signed in with authorized vehicle access.
- **Far-side helpers:** take the iPhone with Bluefy and the other Android with
  Chrome. Both need Bluetooth, internet, and Tailscale access to the near-side
  Mac's private HTTPS endpoint. Neither needs the Tesla app or a USB cable.
- **Vehicle:** confirm the intended local car at the start. Bring a working key
  card for any touchscreen deletion/authentication prompt.

Obtain the owner's authorization before removing the spare Android's existing
phone key. Leave it intact until a browser diagnostic passes and an immediate
enrollment attempt is ready. Preserve every other key and the signed-in
Tesla app; do not clear app data or remove account/driver access.

## Run order

1. **Baseline:** record the spare phone's exact key-list entry on Controls → Locks
   and verify the vehicle selected in the spare phone's app. Confirm no apartment
   fixture or leftover relay is running. Prepare a new HTTPS endpoint/session,
   preserving unrelated Tailscale Serve configuration.
2. **Android diagnostic:** start a fresh car-targeted invitation. In Chrome,
   choose the intended vehicle, compare/approve the code, then verify real GATT
   connection, service/characteristic discovery, and response subscription.
   Do not start the near-side Mac enrollment proxy or send probe payloads.
   End the browser and server session.
3. **iPhone diagnostic:** repeat with a new invitation in Bluefy. End the session.
   If a browser fails this gate, diagnose that failure rather than removing a key
   and attempting enrollment through an unverified connection.
4. **Android enrollment:** after a successful Android diagnostic, remove only the
   spare phone's key and verify both the vehicle key list and app setup state.
   Try the official app's specific phone-key removal/reset option if available;
   if vehicle deletion is needed, guide the owner through deleting that exact
   entry on the touchscreen and authenticating the deletion. Start a new browser
   session, wait for connection, then start the near-side Mac proxy and initiate
   Set Up in the official app. Record app result and new key-list entry. Stop
   forwarding immediately after the attempt.
5. **iPhone enrollment:** only if the iPhone diagnostic passed, remove that same
   newly enrolled test key, verify reset state, and repeat with a fresh Bluefy
   session. Record app and key-list evidence separately. Stop forwarding.
6. **Finish:** leave the spare phone in a known state, preferably successfully
   enrolled. Stop all test forwarding, remove temporary session secrets, and
   remove only the Tailscale endpoint created for the session. Direct entry and
   driving must be tested separately with the enrolled phone physically beside
   the car and both relay endpoints stopped.

Each browser attempt uses a single-use invitation. Changing helper devices,
closing a tab, cancelling a chooser, or disconnecting requires reopening the
original unclaimed invitation or starting a new session if already claimed.
No echo fixtures or arbitrary payload probes may target the car.

Tesla's documented deletion flow is Controls → Locks → the selected key's trash
icon → scan an authenticated key when prompted:
[Managing Keys](https://service.tesla.com/docs/Public/diy/model3/en_us/GUID-67E192C9-4308-44B7-899F-65344F487F1B.html).
Key-card requirements for deletion are separate from app-assisted enrollment.

## What the helper UI establishes

The four steps are Choose, Confirm, Connect, and Wait. Connection steps show the
actual operation and waiting time; pending operations have activity indicators
and timeouts. Connected means the browser link is ready. It does not establish
that enrollment succeeded. Confirm success in the official app and vehicle key
list before ending the session. Diagnostic mode is labeled separately and never
instructs the helper to perform key setup.
