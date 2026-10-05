export const SERVICE = '00000211-b2d1-43f0-9b88-960cebf8b91e';
export const TX = '00000212-b2d1-43f0-9b88-960cebf8b91e';
export const RX = '00000213-b2d1-43f0-9b88-960cebf8b91e';
export function fromHex(hex) {
  if (typeof hex !== 'string' || !/^(?:[0-9a-f]{2}){1,1024}$/i.test(hex)) throw new Error('Invalid message');
  return Uint8Array.from(hex.match(/../g), v => parseInt(v, 16));
}
export function toHex(data) { return Array.from(data, v => v.toString(16).padStart(2, '0')).join(''); }
export function frame(data) {
  if (!data.length || data.length > 1024) throw new Error('Invalid message size');
  const result = new Uint8Array(data.length + 2);
  result[0] = data.length >> 8; result[1] = data.length & 255; result.set(data, 2);
  return result;
}
export class Decoder {
  constructor() { this.buffer = new Uint8Array(); this.last = 0; }
  feed(data, now = Date.now()) {
    if (this.buffer.length && now - this.last > 1000) { this.buffer = new Uint8Array(); throw new Error('Incomplete Bluetooth message timed out'); }
    this.last = now;
    const joined = new Uint8Array(this.buffer.length + data.length);
    joined.set(this.buffer); joined.set(data, this.buffer.length); this.buffer = joined;
    const messages = [];
    while (this.buffer.length >= 2) {
      const size = (this.buffer[0] << 8) | this.buffer[1];
      if (!size || size > 1024) { this.buffer = new Uint8Array(); throw new Error('Invalid Bluetooth frame'); }
      if (this.buffer.length < size + 2) break;
      messages.push(this.buffer.slice(2, size + 2)); this.buffer = this.buffer.slice(size + 2);
    }
    return messages;
  }
}
export class BleEndpoint {
  constructor(device, notify, fail, progress = () => {}, timeoutMs = 15000) {
    this.device = device; this.notify = notify; this.fail = fail; this.progress = progress;
    this.timeoutMs = timeoutMs; this.decoder = new Decoder(); this.closed = false;
  }
  async step(label, operation) {
    if (this.closed) throw new Error('Bluetooth session ended');
    this.progress(label);
    let timer;
    const pending = Promise.resolve().then(operation).then(value => {
      // Native-backed browsers may finish an operation after its timeout.
      if (this.closed) {
        if (this.device.gatt.connected) this.device.gatt.disconnect();
        throw new Error('Bluetooth session ended');
      }
      return value;
    });
    try {
      return await Promise.race([pending, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out. End this session and retry.`)), this.timeoutMs);
      })]);
    } catch (error) {
      this.close();
      throw new Error(`${label}: ${error.message || error}`);
    } finally { clearTimeout(timer); }
  }
  async connect(expectedName) {
    if (this.device.name !== expectedName) throw new Error('Selected vehicle does not match this invitation. Ask the host for a new session.');
    this.device.addEventListener('gattserverdisconnected', this.fail);
    const server = await this.step('Connecting Bluetooth', () => this.device.gatt.connect());
    const service = await this.step('Finding Bluetooth service', () => server.getPrimaryService(SERVICE));
    this.tx = await this.step('Finding write characteristic', () => service.getCharacteristic(TX));
    this.rx = await this.step('Finding response characteristic', () => service.getCharacteristic(RX));
    this.listener = event => {
      try {
        const value = event.target.value;
        const data = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
        for (const message of this.decoder.feed(data)) this.notify(message);
        clearTimeout(this.fragmentTimer);
        if (this.decoder.buffer.length) this.fragmentTimer = setTimeout(() => this.fail(new Error('Incomplete Bluetooth message timed out')), 1100);
      } catch (error) { this.fail(error); }
    };
    this.rx.addEventListener('characteristicvaluechanged', this.listener);
    await this.step('Subscribing to Bluetooth responses', () => this.rx.startNotifications());
  }
  async write(data) {
    // Web Bluetooth has no portable MTU API. 20-byte chunks work at the minimum ATT MTU.
    const bytes = frame(data);
    for (let i = 0; i < bytes.length; i += 20) {
      const part = bytes.slice(i, i + 20);
      if (this.tx.properties.writeWithoutResponse && this.tx.writeValueWithoutResponse) await this.tx.writeValueWithoutResponse(part);
      else if (this.tx.writeValueWithResponse) await this.tx.writeValueWithResponse(part);
      else await this.tx.writeValue(part); // older native-backed browsers
    }
  }
  close() {
    this.closed = true;
    clearTimeout(this.fragmentTimer);
    this.device.removeEventListener('gattserverdisconnected', this.fail);
    if (this.rx && this.listener) this.rx.removeEventListener('characteristicvaluechanged', this.listener);
    if (this.device.gatt.connected) this.device.gatt.disconnect();
  }
}
export class SimulatedEndpoint {
  constructor(notify) { this.notify = notify; this.decoder = new Decoder(); }
  async connect() {}
  async write(data) {
    // Exercise both framing and fragmentation without creating a Bluetooth connection.
    const framed = frame(data);
    for (let i = 0; i < framed.length; i += 20) {
      for (const message of this.decoder.feed(framed.slice(i, i + 20))) this.notify(message);
    }
  }
  close() {}
}
