import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../phone_key_lab/web/transport.js', import.meta.url), 'utf8');
const {frame, Decoder, fromHex, toHex, BleEndpoint, SimulatedEndpoint, TX, RX} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const sizes = [1, 19, 20, 21, 255, 512, 1024];
let notifications = [];
const simulated = new SimulatedEndpoint(data => notifications.push(toHex(data)));
for (const size of sizes) {
  const data = Uint8Array.from({length: size}, (_, i) => i % 256);
  await simulated.write(data);
  assert.equal(notifications.pop(), toHex(data));
}
for (const hex of ['zz', '', 'a', '00'.repeat(1025)]) assert.throws(() => fromHex(hex));
const stale = new Decoder(); stale.feed(frame(fromHex('aabb')).slice(0, 3), 0);
assert.throws(() => stale.feed(new Uint8Array([1]), 1001));
// Emulate GATT to verify queued minimum-MTU writes and fragmented indications.
let writes = [], subscribed = false, listener, disconnected = false;
const tx = {properties: {writeWithoutResponse: true}, async writeValueWithoutResponse(data) { writes.push(data); }};
const rx = {addEventListener(_, fn) {listener = fn;}, removeEventListener(){}, async startNotifications(){subscribed = true;}};
const device = {name: 'SfixtureC', addEventListener(){}, removeEventListener(){}, gatt: {connected: true, async connect(){return {async getPrimaryService(){return {async getCharacteristic(uuid){return uuid === TX ? tx : rx;}};}};}, disconnect(){disconnected = true;}}};
const ble = new BleEndpoint(device, data => notifications.push(toHex(data)), error => {throw error;});
await ble.connect('SfixtureC'); assert.equal(subscribed, true);
const large = Uint8Array.from({length: 1024}, (_, i) => i % 256);
await ble.write(large);
assert.equal(writes.length, 52); assert(writes.every(part => part.length <= 20));
assert.deepEqual(Buffer.concat(writes.map(part => Buffer.from(part))), Buffer.from(frame(large)));
const response = frame(large);
for (let i = 0; i < response.length; i += 13) {
  const part = response.slice(i, i + 13);
  listener({target: {value: new DataView(part.buffer)}});
}
assert.equal(notifications.pop(), toHex(large));
await assert.rejects(new BleEndpoint(device, () => {}, () => {}).connect('Wrong vehicle'), /does not match/);
ble.close(); assert.equal(disconnected, true);
// A native browser operation can hang and then resolve after the session ends.
let finishConnect, lateDisconnected = false, stages = [];
const stalled = {name: 'SfixtureC', addEventListener(){}, removeEventListener(){},
  gatt: {connected: false, connect(){return new Promise(resolve => {finishConnect = resolve;});},
    disconnect(){this.connected = false; lateDisconnected = true;}}};
const timed = new BleEndpoint(stalled, () => {}, () => {}, stage => stages.push(stage), 10);
await assert.rejects(timed.connect('SfixtureC'), /Connecting Bluetooth.*timed out/);
assert.deepEqual(stages, ['Connecting Bluetooth']);
stalled.gatt.connected = true;
finishConnect({getPrimaryService(){throw new Error('Must not continue after timeout');}});
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(lateDisconnected, true); assert.equal(stalled.gatt.connected, false);
console.log('PASS: browser framing, seven echo sizes, stale/invalid frames, 52 minimum-MTU writes, fragmented indications, vehicle mismatch, disconnect.');
