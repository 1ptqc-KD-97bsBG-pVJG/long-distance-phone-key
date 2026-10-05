import AppKit
import Darwin
import CoreBluetooth
import Network
import CryptoKit

let serviceID = CBUUID(string: "00000211-b2d1-43f0-9b88-960cebf8b91e")
let advertisingID = CBUUID(string: "1122")
let txID = CBUUID(string: "00000212-b2d1-43f0-9b88-960cebf8b91e")
let rxID = CBUUID(string: "00000213-b2d1-43f0-9b88-960cebf8b91e")

extension Data {
    var hex: String { map { String(format: "%02x", $0) }.joined() }
    init?(hex: String) {
        guard hex.count % 2 == 0, hex.count <= 2048 else { return nil }
        var result = Data()
        var i = hex.startIndex
        while i < hex.endIndex {
            let end = hex.index(i, offsetBy: 2)
            guard let byte = UInt8(hex[i..<end], radix: 16) else { return nil }
            result.append(byte)
            i = end
        }
        self = result
    }
}

final class Proxy: NSObject, CBPeripheralManagerDelegate {
    let report: (String) -> Void
    var manager: CBPeripheralManager!
    var socket: NWConnection?
    var rx: CBMutableCharacteristic?
    var phone: CBCentral?
    var wireBuffer = Data()
    var bleBuffer = Data()
    var lastFragment = Date()
    var pending: [Data] = []
    var ready = false
    var running = false
    var servicesAdded = false
    var name = "PKLab"
    var mode = "both"
    var token = ""
    var generation = 0
    var handshakeTimer: DispatchWorkItem?
    var fragmentTimer: DispatchWorkItem?
    var outboundCount = 0
    // Apartment diagnostic only: keep discovery available and forward no payloads.
    var discoveryOnly = false
    var diagnosticCentrals: [UUID: Int] = [:]
    func diagnosticLabel(_ central: CBCentral) -> String {
        if diagnosticCentrals[central.identifier] == nil {
            diagnosticCentrals[central.identifier] = diagnosticCentrals.count + 1
        }
        return "client #\(diagnosticCentrals[central.identifier]!)"
    }

    init(report: @escaping (String) -> Void) {
        self.report = report
        super.init()
        manager = CBPeripheralManager(delegate: self, queue: .main)
        report("Bluetooth authorization: \(CBManager.authorization.rawValue) (0 = awaiting permission, 3 = allowed)")
    }

    func start(name: String, mode: String, port: UInt16, token: String) {
        stop()
        guard !name.isEmpty, name.utf8.count <= 29, token.count >= 32 else {
            report("Choose a name of 1..29 bytes and a token of at least 32 characters.")
            return
        }
        self.name = name; self.mode = mode; self.token = token
        running = true
        let epoch = generation
        let connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
        socket = connection
        connection.stateUpdateHandler = { [weak self] state in
            guard let self, self.generation == epoch, self.running else { return }
            switch state {
            case .ready:
                self.report("Relay connected; authenticating")
                self.send(["type": "hello", "token": token])
                self.receive(epoch: epoch)
            case .failed(let error): self.fail("Relay connection failed: \(error)")
            default: break
            }
        }
        connection.start(queue: .main)
        let timer = DispatchWorkItem { [weak self] in
            guard let self, self.running, self.generation == epoch, !self.ready else { return }
            self.fail("Relay connection/authentication timed out")
        }
        handshakeTimer = timer
        DispatchQueue.main.asyncAfter(deadline: .now() + 45, execute: timer)
        report("Connecting to 127.0.0.1:\(port). Cross-laptop connections use an SSH tunnel.")
    }

    func stop() {
        generation += 1
        running = false; ready = false; servicesAdded = false
        handshakeTimer?.cancel(); handshakeTimer = nil
        fragmentTimer?.cancel(); fragmentTimer = nil
        if manager?.state == .poweredOn {
            manager.stopAdvertising()
            manager.removeAllServices()
        }
        socket?.cancel(); socket = nil
        phone = nil; rx = nil
        wireBuffer.removeAll(); bleBuffer.removeAll(); pending.removeAll()
        outboundCount = 0
    }

    func fail(_ message: String) { report("STOPPED: \(message). Restart for a fresh session."); stop() }

    func send(_ packet: [String: Any]) {
        guard let socket, var data = try? JSONSerialization.data(withJSONObject: packet) else { return }
        guard outboundCount < 128 else { fail("Relay send queue full"); return }
        outboundCount += 1
        data.append(10)
        let epoch = generation
        socket.send(content: data, completion: .contentProcessed { [weak self] error in
            guard let self, self.generation == epoch else { return }
            self.outboundCount -= 1
            if let error { self.fail("Relay write failed: \(error)") }
        })
    }

    func receive(epoch: Int) {
        socket?.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] data, _, complete, error in
            guard let self, self.generation == epoch, self.running else { return }
            if let data {
                self.wireBuffer.append(data)
                while let newline = self.wireBuffer.firstIndex(of: 10) {
                    let line = self.wireBuffer[..<newline]
                    self.wireBuffer.removeSubrange(...newline)
                    guard line.count <= 4096,
                          let packet = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                          let kind = packet["type"] as? String else { self.fail("Malformed relay packet"); return }
                    if kind == "ready", !self.ready {
                        self.ready = true
                        self.handshakeTimer?.cancel()
                        self.report("Backend ready: \(packet["backend"] ?? "unknown")")
                        self.publish()
                    } else if kind == "notify", self.ready,
                              let hex = packet["data"] as? String,
                              let payload = Data(hex: hex), !payload.isEmpty {
                        guard self.phone != nil else {
                            self.report("Discarded unsolicited vehicle message before phone subscription: \(payload.count) bytes")
                            continue
                        }
                        guard self.pending.count < 128 else { self.fail("Notification queue full"); return }
                        var framed = Data([UInt8(payload.count >> 8), UInt8(payload.count & 255)])
                        framed.append(payload)
                        self.pending.append(framed)
                        self.report("Vehicle → phone: \(payload.count) bytes")
                        self.flush()
                    } else if kind == "error" {
                        self.fail(packet["message"] as? String ?? "Relay error"); return
                    } else { self.fail("Unexpected relay packet: \(kind)"); return }
                    if !self.running { return }
                }
                if self.wireBuffer.count > 4096 { self.fail("Relay packet too large"); return }
            }
            if let error { self.fail("Relay receive failed: \(error)"); return }
            if complete { self.fail("Relay disconnected"); return }
            self.receive(epoch: epoch)
        }
    }

    func publish() {
        guard running, ready, manager.state == .poweredOn, !servicesAdded else { return }
        servicesAdded = true
        let tx = CBMutableCharacteristic(type: txID, properties: [.write, .writeWithoutResponse], value: nil, permissions: [.writeable])
        let rx = CBMutableCharacteristic(type: rxID, properties: [.notify, .indicate], value: nil, permissions: [])
        self.rx = rx
        let service = CBMutableService(type: serviceID, primary: true)
        service.characteristics = [tx, rx]
        manager.add(service)
    }

    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        report("Bluetooth state: \(peripheral.state.rawValue) (5 = powered on)")
        if peripheral.state == .poweredOn { publish() }
        else if running && peripheral.state != .unknown && peripheral.state != .resetting {
            fail("Bluetooth is unavailable or permission has not been granted")
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        guard running else { return }
        if let error { fail("Service publication failed: \(error)"); return }
        var advertisement: [String: Any] = [:]
        if mode != "service-only" { advertisement[CBAdvertisementDataLocalNameKey] = name }
        if mode != "name-only" { advertisement[CBAdvertisementDataServiceUUIDsKey] = [mode == "tesla-name" ? advertisingID : serviceID] }
        peripheral.startAdvertising(advertisement)
    }

    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        if let error { fail("Advertising failed: \(error)") }
        else { report("ADVERTISING: \(name) [\(mode)]. Ready for the Android phone.") }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didSubscribeTo characteristic: CBCharacteristic) {
        guard running, ready else { return }
        if discoveryOnly {
            report("DIAGNOSTIC subscription from \(diagnosticLabel(central)); advertising active: \(peripheral.isAdvertising); payload forwarding disabled")
            return
        }
        if let phone, phone.identifier != central.identifier { fail("A second phone subscribed"); return }
        phone = central
        peripheral.stopAdvertising()
        report("Phone subscribed; maximum notification size \(central.maximumUpdateValueLength)")
        flush()
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didUnsubscribeFrom characteristic: CBCharacteristic) {
        if discoveryOnly { report("Diagnostic \(diagnosticLabel(central)) unsubscribed"); return }
        if phone?.identifier == central.identifier { fail("Phone unsubscribed") }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        guard let first = requests.first else { return }
        if discoveryOnly {
            report("DIAGNOSTIC rejected payload writes from \(diagnosticLabel(first.central)); advertising active: \(peripheral.isAdvertising)")
            peripheral.respond(to: first, withResult: .writeNotPermitted)
            return
        }
        report("BLE write received: \(requests.count) request(s), \(requests.reduce(0) { $0 + ($1.value?.count ?? 0) }) bytes")
        guard running, ready, let phone, requests.allSatisfy({ $0.central.identifier == phone.identifier && $0.characteristic.uuid == txID && $0.offset == 0 && $0.value != nil }) else {
            report("Rejected write: inactive session, unexpected central, characteristic, or offset")
            peripheral.respond(to: first, withResult: .unlikelyError)
            return
        }
        if !bleBuffer.isEmpty && Date().timeIntervalSince(lastFragment) > 1 {
            peripheral.respond(to: first, withResult: .unlikelyError)
            fail("Incomplete phone message timed out"); return
        }
        lastFragment = Date()
        for request in requests { bleBuffer.append(request.value!) }
        var messages: [Data] = []
        while bleBuffer.count >= 2 {
            let bytes = Array(bleBuffer.prefix(2))
            let count = Int(bytes[0]) * 256 + Int(bytes[1])
            guard count > 0 && count <= 1024 else {
                peripheral.respond(to: first, withResult: .invalidAttributeValueLength)
                fail("Malformed phone message"); return
            }
            if bleBuffer.count < count + 2 { break }
            messages.append(Data(bleBuffer.dropFirst(2).prefix(count)))
            bleBuffer.removeFirst(count + 2)
        }
        peripheral.respond(to: first, withResult: .success)
        for message in messages {
            report("Phone → vehicle: \(message.count) bytes")
            send(["type": "write", "data": message.hex])
        }
        fragmentTimer?.cancel()
        if !bleBuffer.isEmpty {
            let epoch = generation
            let timer = DispatchWorkItem { [weak self] in
                guard let self, self.generation == epoch, !self.bleBuffer.isEmpty else { return }
                self.fail("Incomplete phone message timed out")
            }
            fragmentTimer = timer
            DispatchQueue.main.asyncAfter(deadline: .now() + 1, execute: timer)
        }
    }

    func flush() {
        guard let phone, let rx, running else { return }
        while !pending.isEmpty {
            let chunk = Data(pending[0].prefix(min(512, phone.maximumUpdateValueLength)))
            if !manager.updateValue(chunk, for: rx, onSubscribedCentrals: [phone]) { return }
            pending[0].removeFirst(chunk.count)
            if pending[0].isEmpty { pending.removeFirst() }
        }
    }
    func peripheralManagerIsReady(toUpdateSubscribers peripheral: CBPeripheralManager) { flush() }
}

final class App: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var logView = NSTextView()
    var nameField = NSTextField(string: "PKLab")
    var portField = NSTextField(string: "18765")
    var tokenField = NSTextField(string: FileManager.default.currentDirectoryPath + "/lab.token")
    var modeField = NSPopUpButton()
    var proxy: Proxy!
    var activity = NSProgressIndicator()
    var statusLabel = NSTextField(labelWithString: "Ready to start")

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 600), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Phone Key Proxy — experimental transport"
        let stack = NSStackView()
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -20)
        ])
        let description = NSTextField(wrappingLabelWithString: "Start after the helper connects. Use a simulator for echo tests.")
        stack.addArrangedSubview(description)
        for (label, field) in [("Advertised name", nameField), ("Local relay port", portField), ("Token file", tokenField)] {
            let row = NSStackView(views: [NSTextField(labelWithString: label), field])
            row.orientation = .horizontal
            field.widthAnchor.constraint(equalToConstant: 490).isActive = true
            stack.addArrangedSubview(row)
        }
        modeField.addItems(withTitles: ["both", "name-only", "service-only", "tesla-name"])
        stack.addArrangedSubview(modeField)
        let start = NSButton(title: "Start proxy", target: self, action: #selector(startProxy))
        let stop = NSButton(title: "Stop", target: self, action: #selector(stopProxy))
        stack.addArrangedSubview(NSStackView(views: [start, stop]))
        activity.style = .spinning; activity.controlSize = .small; activity.isDisplayedWhenStopped = false
        statusLabel.font = NSFont.systemFont(ofSize: 14, weight: .medium)
        stack.addArrangedSubview(NSStackView(views: [activity, statusLabel]))
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        logView.isEditable = false
        logView.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        logView.textColor = .labelColor
        logView.backgroundColor = .textBackgroundColor
        scroll.documentView = logView
        stack.addArrangedSubview(scroll)
        scroll.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 300).isActive = true
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        proxy = Proxy { [weak self] text in self?.report(text) }
        let args = CommandLine.arguments
        func option(_ key: String) -> String? {
            guard let i = args.firstIndex(of: key), i + 1 < args.count else { return nil }
            return args[i + 1]
        }
        if let name = option("--name") { nameField.stringValue = name }
        if let port = option("--port") { portField.stringValue = port }
        if let path = option("--token-file") { tokenField.stringValue = path }
        if let mode = option("--mode"), ["both", "name-only", "service-only", "tesla-name"].contains(mode) { modeField.selectItem(withTitle: mode) }
        if args.contains("--discovery-only") {
            proxy.discoveryOnly = true
            report("APARTMENT DISCOVERY ONLY: no payload forwarding; advertising stays active")
        }
        if args.contains("--auto-start") { startProxy() }
    }
    func report(_ text: String) {
        if text.hasPrefix("Connecting to") {
            statusLabel.stringValue = "Connecting to relay…"; activity.startAnimation(nil)
        } else if text.hasPrefix("ADVERTISING:") {
            statusLabel.stringValue = proxy?.discoveryOnly == true ? "Bluetooth diagnostic ready" : "Waiting for phone…"
            activity.startAnimation(nil)
        } else if text.hasPrefix("Phone subscribed") || text.hasPrefix("DIAGNOSTIC subscription") {
            statusLabel.stringValue = proxy?.discoveryOnly == true ? "Diagnostic client connected" : "Phone connected"
            activity.stopAnimation(nil)
        } else if text == "Stopped" || text.hasPrefix("ERROR:") {
            statusLabel.stringValue = text == "Stopped" ? "Stopped" : text
            activity.stopAnimation(nil)
        }
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(text)\n"
        print(line, terminator: "")
        logView.textStorage?.append(NSAttributedString(string: line, attributes: [
            .foregroundColor: NSColor.labelColor,
            .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        ]))
        logView.scrollToEndOfDocument(nil)
    }
    @objc func startProxy() {
        do {
            guard let port = UInt16(portField.stringValue), port > 0 else { report("Invalid port"); return }
            let token = try String(contentsOfFile: tokenField.stringValue, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            proxy.start(name: nameField.stringValue, mode: modeField.titleOfSelectedItem ?? "both", port: port, token: token)
        } catch { report("Cannot read token file: \(error)") }
    }
    @objc func stopProxy() { proxy.stop(); report("Stopped") }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { proxy.stop() }
}

setbuf(stdout, nil)
let application = NSApplication.shared
application.setActivationPolicy(.regular)
let delegate = App()
application.delegate = delegate
application.run()
