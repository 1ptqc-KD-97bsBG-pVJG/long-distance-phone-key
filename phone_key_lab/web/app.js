import {SERVICE, fromHex, toHex, BleEndpoint, SimulatedEndpoint} from './transport.js';
import {show} from './ui.js';
const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.hash.slice(1));
const token = params.get('invite') || location.hash.slice(1);
const simulation = params.get('demo') === '1';
const diagnostic = params.get('test') === '1';
history.replaceState(null, '', location.pathname);
addEventListener('hashchange', () => { if (location.hash) location.reload(); });
let socket, endpoint, wake, joinTimer, stopped = false, queue = Promise.resolve(), pending = 0;
async function stop(title = 'Session ended.', detail = 'You can close this page.', error = false) {
  if (stopped) return;
  stopped = true; clearTimeout(joinTimer); endpoint?.close(); socket?.close(); await wake?.release().catch(() => {});
  $('connect').hidden = true; $('stop').hidden = true; $('code-wrap').hidden = true;
  show({title, detail, icon: error ? 'alert' : 'check', tone: error ? 'error' : 'normal'});
}
function fail(error) { return stop('Couldn’t connect.', error.message || String(error), true); }
function notify(data) {
  if (socket?.readyState !== WebSocket.OPEN || socket.bufferedAmount > 65536) throw new Error('Connection unavailable');
  socket.send(JSON.stringify({type: 'notify', data: toHex(data)}));
}
$('stop').onclick = () => stop();
if (simulation || diagnostic) {
  $('mode').hidden = false; $('mode').textContent = simulation ? 'Simulation' : 'Bluetooth test';
  document.querySelector('.intro').textContent = simulation ? 'No car or Bluetooth needed.' : 'Connect to the test device.';
}
if (!token) {
  $('connect').hidden = true;
  show({title: 'Open your invitation.', detail: 'Use the full link sent by the other person.', icon: 'link'});
} else if (!simulation && (!isSecureContext || !navigator.bluetooth)) {
  $('connect').hidden = true; document.querySelector('.help').open = true;
  show({title: 'Use a Bluetooth browser.', detail: 'iPhone: Bluefy. Android: Chrome over HTTPS.', icon: 'alert', tone: 'error'});
} else {
  $('connect').disabled = false; $('connect').textContent = simulation ? 'Start test' : 'Connect';
  show({title: simulation ? 'Ready to test.' : diagnostic ? 'Find the test device.' : 'Choose the car.',
    detail: simulation ? 'Start the apartment test.' : diagnostic ? 'Select the device named by your host.' : 'Select only the owner’s vehicle.', step: 1, icon: 'car'});
}
$('connect').onclick = async () => {
  $('connect').disabled = true; $('connect').hidden = true; $('stop').hidden = false;
  show({title: simulation ? 'Starting test…' : 'Choose a device.', detail: 'Select it in the Bluetooth list.', step: 1, icon: 'bluetooth', busy: true});
  try {
    // Keep the chooser in the user's gesture, before any network await.
    const device = simulation ? null : await navigator.bluetooth.requestDevice({filters: [{namePrefix: 'S'}], optionalServices: [SERVICE]});
    if (stopped) return;
    show({title: 'Reaching the other person…', detail: 'Keep this page open.', step: 2, icon: 'link', busy: true});
    try { wake = await navigator.wakeLock?.request('screen'); } catch { /* instructions remain visible */ }
    if (stopped) return;
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/relay`);
    joinTimer = setTimeout(() => fail(new Error('The host did not respond. Ask for a fresh invitation.')), 10000);
    socket.onopen = () => { if (!stopped) socket.send(JSON.stringify({type: 'join', token})); };
    socket.onclose = () => stop('Connection closed.', 'Ask for a fresh invitation to retry.');
    socket.onerror = () => fail(new Error('The host is unreachable. Check your connection.'));
    socket.onmessage = event => {
      if (stopped) return;
      try {
        const packet = JSON.parse(event.data);
        if (packet.type === 'waiting') {
          clearTimeout(joinTimer); $('code').textContent = packet.code; $('code-wrap').hidden = false;
          show({title: 'Confirm together.', detail: 'Read the code to the other person.', step: 2, icon: 'code', busy: true});
        } else if (packet.type === 'approved') {
          clearTimeout(joinTimer);
          if (packet.simulation !== simulation || Boolean(packet.diagnostic) !== diagnostic) throw new Error('Invitation mode mismatch');
          $('code-wrap').hidden = true;
          endpoint = simulation ? new SimulatedEndpoint(notify) : new BleEndpoint(device, notify,
            error => fail(error instanceof Error ? error : new Error('Bluetooth disconnected.')),
            stage => show({title: 'Connecting…', detail: `${stage}…`, step: 3, icon: 'bluetooth', busy: true}));
          show({title: 'Connecting…', detail: 'Opening the Bluetooth connection.', step: 3, icon: 'bluetooth', busy: true});
          queue = queue.then(async () => {
            await endpoint.connect(packet.name);
            if (stopped) { endpoint.close(); return; }
            socket.send(JSON.stringify({type: 'ready'}));
            show({title: 'Connected.', detail: simulation ? 'Ready for the echo test.' : diagnostic ? 'Bluetooth test ready. No key setup.' : 'Wait while the other person sets up their phone.', step: 4, icon: 'link', busy: !simulation && !diagnostic});
          }).catch(fail);
        } else if (packet.type === 'write') {
          if (!endpoint || ++pending > 64) throw new Error('Too many pending messages');
          const data = fromHex(packet.data);
          queue = queue.then(() => { if (!stopped) return endpoint.write(data); }).finally(() => pending--).catch(fail);
        } else throw new Error('Unexpected session message');
      } catch (error) { fail(error); }
    };
  } catch (error) {
    if (error.name === 'NotFoundError') await stop('Nothing selected.', 'Open the original invitation to try again.');
    else await fail(error);
  }
};
addEventListener('pagehide', () => { clearTimeout(joinTimer); endpoint?.close(); socket?.close(); });
