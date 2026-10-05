import {show} from './ui.js';
const $ = id => document.getElementById(id);
const key = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
const headers = {Authorization: `Bearer ${key}`};
let ended = false, refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const response = await fetch('/api/status', {headers, cache: 'no-store'});
    if (!response.ok) throw new Error('Open the original private host link from Terminal.');
    const session = await response.json();
    $('mode').textContent = session.simulation ? 'Simulation' : session.diagnostic ? 'Bluetooth test' : 'Host';
    $('code').textContent = session.code || ''; $('code-wrap').hidden = !session.claimed || session.approved || session.ended;
    $('approve').hidden = !session.claimed || session.approved || session.ended;
    $('approve').disabled = !session.claimed || session.approved || session.ended;
    $('end').disabled = session.ended;
    const seconds = session.seconds_left;
    $('expiry').textContent = session.ended ? 'Session closed.' : `Expires in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (session.ended) show({title: 'Session ended.', detail: 'Start a new session for a fresh invitation.', icon: 'check'});
    else if (session.ready) show({title: 'Helper connected.', detail: session.diagnostic ? 'Bluetooth diagnostic ready.' : session.simulation ? 'Run the apartment echo test.' : 'Start the Mac proxy, then phone setup.', step: 4, icon: 'link'});
    else if (session.approved) show({title: 'Connecting Bluetooth…', detail: 'The helper is connecting to the device.', step: 3, icon: 'bluetooth', busy: true});
    else if (session.claimed) show({title: 'Check the code.', detail: 'Approve only if your helper reads the same code.', step: 2, icon: 'code'});
    else show({title: 'Waiting for your helper.', detail: 'Send the invitation from Terminal.', step: 1, icon: 'link', busy: true});
    ended = session.ended;
  } catch (error) {
    show({title: 'Host unavailable.', detail: error.message, icon: 'alert', tone: 'error'});
    $('approve').disabled = true; $('end').disabled = true;
  } finally { refreshing = false; }
}
for (const action of ['approve', 'end']) $(action).onclick = async () => {
  $(action).disabled = true;
  try {
    const response = await fetch(`/api/${action}`, {method: 'POST', headers});
    if (!response.ok) throw new Error('Action unavailable. Open the original host link.');
    await refresh();
  } catch (error) { show({title: 'Action unavailable.', detail: error.message, icon: 'alert', tone: 'error'}); }
};
refresh();
setInterval(() => { if (!ended) refresh(); }, 1000);
