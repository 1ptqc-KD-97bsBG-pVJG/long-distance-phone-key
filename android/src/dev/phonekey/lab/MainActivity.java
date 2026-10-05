package dev.phonekey.lab;

import android.Manifest;
import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.pm.PackageManager;
import android.util.Log;
import android.view.View;
import android.widget.*;
import java.io.ByteArrayOutputStream;
import java.util.*;

/** A transport test client. It never enrolls a key or sends Tesla commands. */
public class MainActivity extends Activity {
    static final UUID SERVICE = UUID.fromString("00000211-b2d1-43f0-9b88-960cebf8b91e");
    static final UUID TX = UUID.fromString("00000212-b2d1-43f0-9b88-960cebf8b91e");
    static final UUID RX = UUID.fromString("00000213-b2d1-43f0-9b88-960cebf8b91e");
    static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    final Handler handler = new Handler(Looper.getMainLooper());
    final int[] sizes = {1, 19, 20, 21, 255, 512, 1024};
    TextView output;
    EditText target;
    ProgressBar activity;
    BluetoothLeScanner scanner;
    BluetoothGatt gatt;
    BluetoothGattCharacteristic tx, rx;
    ByteArrayOutputStream incoming = new ByteArrayOutputStream();
    byte[] expected, outgoing;
    int offset, test, passed;
    int requestedMtu = 23, mtu = 23;
    boolean running, found, scanOnly;
    Runnable watchdog = () -> fail("Timed out waiting for scan, GATT operation, or response");
    Runnable scanFinished = () -> {
        if (!running || !scanOnly) return;
        line(found ? "PASS: advertisement observed; no connection or writes performed"
                   : "No matching advertisement observed during 15-second scan");
        stop();
    };

    void line(String text) {
        Log.i("PhoneKeyLab", text);
        handler.post(() -> output.append(text + "\n"));
    }
    void arm() { handler.removeCallbacks(watchdog); handler.postDelayed(watchdog, 20000); }
    void fail(String text) {
        if (!running) return;
        line("FAIL: " + text);
        stop();
    }
    void stop() {
        running = false;
        if (activity != null) activity.setVisibility(View.GONE);
        handler.removeCallbacks(watchdog);
        handler.removeCallbacks(scanFinished);
        if (scanner != null) scanner.stopScan(scan);
        if (gatt != null) { gatt.disconnect(); gatt.close(); gatt = null; }
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(28, 40, 28, 28);
        TextView title = new TextView(this);
        title.setText("Phone Key Lab");
        title.setTextSize(22);
        layout.addView(title);
        TextView description = new TextView(this);
        description.setText("Echo: simulator only. Scan: no connection or writes.\n\nDevice name:");
        layout.addView(description);
        target = new EditText(this);
        target.setSingleLine(true);
        target.setText("PKLab");
        layout.addView(target);
        Button run = new Button(this);
        run.setText("Run echo test");
        run.setOnClickListener(v -> { requestedMtu = 23; begin(); });
        layout.addView(run);
        Button largeMtu = new Button(this);
        largeMtu.setText("Run with larger MTU");
        largeMtu.setOnClickListener(v -> { requestedMtu = 247; begin(); });
        layout.addView(largeMtu);
        Button scanButton = new Button(this);
        scanButton.setText("Scan only — no connection");
        scanButton.setOnClickListener(v -> begin(true));
        layout.addView(scanButton);
        activity = new ProgressBar(this);
        activity.setContentDescription("Bluetooth operation in progress");
        activity.setVisibility(View.GONE);
        layout.addView(activity);
        output = new TextView(this);
        output.setTextSize(15);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(output);
        layout.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
    }
    void begin() {
        begin(false);
    }
    void begin(boolean passive) {
        if (running) return;
        if (android.os.Build.VERSION.SDK_INT >= 31 &&
            (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED ||
             checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED)) {
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT}, 1);
            return;
        }
        if (android.os.Build.VERSION.SDK_INT < 31 && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, 1);
            return;
        }
        BluetoothAdapter adapter = getSystemService(BluetoothManager.class).getAdapter();
        output.setText("");
        running = true; found = false; scanOnly = passive; test = 0; passed = 0; mtu = 23;
        activity.setVisibility(View.VISIBLE);
        incoming.reset();
        if (adapter == null || !adapter.isEnabled()) { fail("Enable Bluetooth first"); return; }
        scanner = adapter.getBluetoothLeScanner();
        line("Scanning for " + target.getText().toString());
        scanner.startScan(Collections.singletonList(new ScanFilter.Builder().setDeviceName(target.getText().toString()).build()),
            new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scan);
        if (scanOnly) {
            line("Advertisement scan only: no GATT connection or payload writes");
            handler.postDelayed(scanFinished, 15000);
        } else arm();
    }
    final ScanCallback scan = new ScanCallback() {
        @Override public void onScanResult(int type, ScanResult result) {
            if (!running || found || result.getScanRecord() == null) return;
            String name = result.getScanRecord().getDeviceName();
            if (!target.getText().toString().equals(name)) return;
            found = true;
            if (scanOnly) {
                line("OBSERVED: " + name + "; RSSI " + result.getRssi()
                     + "; services " + result.getScanRecord().getServiceUuids());
                return;
            }
            scanner.stopScan(this);
            line("PASS: advertised name; connecting");
            gatt = result.getDevice().connectGatt(MainActivity.this, false, callback, BluetoothDevice.TRANSPORT_LE);
            arm();
        }
        @Override public void onScanFailed(int code) { fail("scan error " + code); }
    };
    final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
            handler.post(() -> {
                if (!running || g != gatt) return;
                if (status != 0 || state == BluetoothProfile.STATE_DISCONNECTED) { fail("connection status " + status); return; }
                if (state == BluetoothProfile.STATE_CONNECTED) {
                    if (requestedMtu > 23) {
                        line("Connected; requesting MTU " + requestedMtu);
                        if (!g.requestMtu(requestedMtu)) fail("MTU request could not start");
                    } else {
                        line("Connected; discovering services");
                        if (!g.discoverServices()) fail("discovery could not start");
                    }
                    arm();
                }
            });
        }
        @Override public void onMtuChanged(BluetoothGatt g, int negotiated, int status) {
            handler.post(() -> {
                if (!running || g != gatt) return;
                if (status != 0 || negotiated < 23) { fail("MTU status " + status); return; }
                mtu = negotiated;
                line("PASS: negotiated MTU " + mtu);
                if (!g.discoverServices()) fail("discovery could not start");
                arm();
            });
        }
        @Override public void onServicesDiscovered(BluetoothGatt g, int status) {
            handler.post(() -> {
                if (!running || g != gatt) return;
                BluetoothGattService service = g.getService(SERVICE);
                if (status != 0 || service == null) { fail("service missing/status " + status); return; }
                tx = service.getCharacteristic(TX); rx = service.getCharacteristic(RX);
                if (tx == null || rx == null) { fail("characteristics missing"); return; }
                line("PASS: service and both characteristics");
                if (!g.setCharacteristicNotification(rx, true)) { fail("notification registration failed"); return; }
                BluetoothGattDescriptor descriptor = rx.getDescriptor(CCCD);
                if (descriptor == null) { fail("CCCD missing"); return; }
                byte[] mode = (rx.getProperties() & BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0
                    ? BluetoothGattDescriptor.ENABLE_INDICATION_VALUE : BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE;
                descriptor.setValue(mode);
                if (!g.writeDescriptor(descriptor)) fail("subscription could not start");
                arm();
            });
        }
        @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) {
            handler.post(() -> {
                if (!running || g != gatt) return;
                if (status != 0) { fail("subscription status " + status); return; }
                line("PASS: response subscription");
                nextTest();
            });
        }
        @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
            handler.post(() -> {
                if (!running || g != gatt) return;
                if (status != 0) { fail("write status " + status); return; }
                writeChunk();
            });
        }
        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) {
            byte[] copy = value.clone();
            handler.post(() -> { if (g == gatt) got(copy); });
        }
        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            if (android.os.Build.VERSION.SDK_INT < 33) {
                byte[] copy = c.getValue().clone();
                handler.post(() -> { if (g == gatt) got(copy); });
            }
        }
    };
    void nextTest() {
        if (test == 21) {
            line("PASS: ALL 21 ECHO EXCHANGES (3 rounds × 7 sizes; 1..1024 bytes)");
            stop();
            return;
        }
        int size = sizes[test % sizes.length];
        expected = new byte[size];
        for (int i = 0; i < size; i++) expected[i] = (byte)(i + test);
        outgoing = new byte[size + 2];
        outgoing[0] = (byte)(size >> 8); outgoing[1] = (byte)size;
        System.arraycopy(expected, 0, outgoing, 2, size);
        offset = 0;
        incoming.reset();
        writeChunk();
        arm();
    }
    void writeChunk() {
        if (offset >= outgoing.length) return;
        byte[] part = Arrays.copyOfRange(outgoing, offset, Math.min(offset + Math.min(512, mtu - 3), outgoing.length));
        offset += part.length;
        tx.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        tx.setValue(part);
        if (!gatt.writeCharacteristic(tx)) fail("write could not start");
    }
    void got(byte[] data) {
        if (!running) return;
        incoming.write(data, 0, data.length);
        byte[] bytes = incoming.toByteArray();
        if (bytes.length < 2) return;
        int size = ((bytes[0] & 255) << 8) | (bytes[1] & 255);
        if (size < 1 || size > 1024 || bytes.length > size + 2) { fail("invalid response framing"); return; }
        if (bytes.length < size + 2) return;
        if (!Arrays.equals(Arrays.copyOfRange(bytes, 2, bytes.length), expected)) { fail("response mismatch"); return; }
        line("PASS: exchange " + (++passed) + ", " + size + " bytes");
        test++;
        handler.postDelayed(() -> { if (running) nextTest(); }, 50);
    }
    @Override public void onDestroy() { stop(); super.onDestroy(); }
}
