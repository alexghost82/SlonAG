import Foundation
import Network
import Security

/// Connection state matching the Python backend.
public enum ConnectivityState: String, Sendable {
    case disconnected
    case connecting
    case connected
    case migrating
    case error
}

/// Transport kind used for the current connection.
public enum TransportKind: String, Sendable {
    case lanTLS = "lan_tls"
    case lanWS = "lan_ws"
    case remote
    case local
}

/// LAN device discovered via Bonjour/mDNS.
public struct LANDevice: Identifiable, Sendable, Equatable {
    public let id = UUID()
    public let name: String
    public let host: String
    public let port: Int
    public let deviceID: String
    public let displayName: String
    public let fingerprint: String
    public let usesTLS: Bool

    public var connectURL: String {
        "\(usesTLS ? "wss" : "ws")://\(host):\(port)"
    }
}

/// A discovery scan result.
public struct LANScanResult: Sendable {
    public let devices: [LANDevice]
    public let timestamp: Date
}

/// Connectivity manager - the single source of truth for connection state on iOS.
///
/// Coordinates:
/// - Bonjour discovery of same-LAN Desktop devices.
/// - TLS/WSS transport for LAN connections.
/// - Remote transport adapter for out-of-LAN.
/// - Transparent LAN <-> remote migration.
/// - Connection health monitoring with auto-reconnect.
@MainActor
public final class ConnectivityManager: @unchecked Sendable {
    public enum Event: Sendable {
        case stateChanged(ConnectivityState)
        case deviceDiscovered(LANDevice)
        case devicesDiscovered([LANDevice])
        case migrationStarted(from: TransportKind, to: TransportKind)
        case migrationCompleted
        case connectionLost
        case reconnected
    }

    public var onEvent: ((Event) -> Void)?

    public private(set) var state: ConnectivityState = .disconnected
    public private(set) var currentTransport: TransportKind = .local
    public private(set) var currentDevice: LANDevice?
    public private(set) var devices: [LANDevice] = []

    private let browser: BonjourBrowser
    private let tlsClient: TLSClient
    private let remoteAdapter: RemoteAdapter
    private let policy: ConnectivityPolicy

    private var reconnectAttempt = 0
    private var monitorTask: Task<Void, Never>?

    // MARK: - Init

    public init(
        policy: ConnectivityPolicy = .default,
        browser: BonjourBrowser? = nil,
        tlsClient: TLSClient? = nil,
        remoteAdapter: RemoteAdapter? = nil
    ) {
        self.policy = policy
        self.browser = browser ?? BonjourBrowser()
        self.tlsClient = tlsClient ?? TLSClient()
        self.remoteAdapter = remoteAdapter ?? RemoteAdapter()

        self.browser.onUpdate = { [weak self] services in
            guard let self else { return }
            Task { @MainActor in
                self.devices = services.compactMap { svc -> LANDevice? in
                    LANDevice(
                        name: svc.name,
                        host: svc.host ?? "",
                        port: svc.port ?? 8765,
                        deviceID: "",
                        displayName: svc.name.split(separator: ".").first?.description ?? "",
                        fingerprint: svc.certificateFingerprint ?? "",
                        usesTLS: svc.usesTLS
                    )
                }
                self.onEvent?(.devicesDiscovered(self.devices))
            }
        }
    }

    // MARK: - Discovery

    public func startDiscovery() {
        browser.start()
    }

    public func stopDiscovery() {
        browser.stop()
        devices.removeAll()
    }

    public func scanDevices() async -> [LANDevice] {
        let foundDevices = devices
        onEvent?(.devicesDiscovered(foundDevices))
        return foundDevices
    }

    // MARK: - Connection lifecycle

    public func connect(to device: LANDevice) async throws {
        guard state != .connecting else {
            throw ConnectivityError.alreadyConnecting
        }

        state = .connecting
        currentDevice = device
        currentTransport = .lanTLS
        onEvent?(.stateChanged(.connecting))

        do {
            try await tlsClient.connect(to: device)
            currentTransport = .lanTLS
            state = .connected
            onEvent?(.stateChanged(.connected))
            onEvent?(.reconnected)
            startMonitoring()
        } catch {
            state = .error
            onEvent?(.stateChanged(.error))
            throw error
        }
    }

    public func disconnect() async {
        stopMonitoring()

        if let device = currentDevice {
            do {
                try await tlsClient.disconnect(from: device)
            } catch {
                _log("Disconnect error: \(error)")
            }
        }

        state = .disconnected
        currentTransport = .local
        currentDevice = nil
        onEvent?(.stateChanged(.disconnected))
    }

    public func reconnect() async throws {
        if let device = currentDevice {
            try await connect(to: device)
        } else {
            let found = await scanDevices()
            guard let best = bestLANDevice(from: found) else {
                throw ConnectivityError.noDevicesAvailable
            }
            try await connect(to: best)
        }
    }

    public func connectRemote() async throws {
        if state != .connecting {
            state = .connecting
            onEvent?(.stateChanged(.connecting))
        }

        do {
            try await remoteAdapter.connect()
            currentTransport = .remote
            state = .connected
            onEvent?(.stateChanged(.connected))
            startMonitoring()
        } catch {
            state = .error
            onEvent?(.stateChanged(.error))
            throw error
        }
    }

    // MARK: - Migration

    public func migrateToLAN(_ device: LANDevice) async throws {
        guard state == .connected && currentTransport == .remote else {
            throw ConnectivityError.invalidMigration(
                "Can only migrate when connected via remote"
            )
        }

        onEvent?(.migrationStarted(from: .remote, to: .lanTLS))
        state = .migrating

        try? await remoteAdapter.disconnect()

        do {
            try await tlsClient.connect(to: device)
            currentTransport = .lanTLS
            currentDevice = device
            state = .connected
            onEvent?(.stateChanged(.connected))
            onEvent?(.migrationCompleted)
        } catch {
            state = .error
            onEvent?(.stateChanged(.error))
            throw error
        }
    }

    public func migrateToRemote() async throws {
        guard state == .connected && currentTransport == .lanTLS else {
            throw ConnectivityError.invalidMigration(
                "Can only migrate when connected via LAN"
            )
        }

        onEvent?(.migrationStarted(from: .lanTLS, to: .remote))
        state = .migrating

        if let device = currentDevice {
            try? await tlsClient.disconnect(from: device)
        }

        try await remoteAdapter.connect()
        currentTransport = .remote

        state = .connected
        onEvent?(.stateChanged(.connected))
        onEvent?(.migrationCompleted)
    }

    // MARK: - Monitoring

    private func startMonitoring() {
        guard monitorTask == nil else { return }
        monitorTask = Task { [weak self] in
            await self?.monitorLoop()
        }
    }

    private func stopMonitoring() {
        monitorTask?.cancel()
        monitorTask = nil
    }

    private func monitorLoop() async {
        let interval: TimeInterval = 15
        while !Task.isCancelled {
            try await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
            if !Task.isCancelled {
                if await isConnectionStale() {
                    await handleStaleConnection()
                }
            }
        }
    }

    private func isConnectionStale() async -> Bool {
        // Check WebSocket pong timestamps - stubbed for now.
        return false
    }

    private func handleStaleConnection() async {
        guard state == .connected else { return }

        if currentTransport == .lanTLS, policy.autoReconnect {
            do {
                try await reconnect()
            } catch {
                state = .error
                onEvent?(.stateChanged(.error))
            }
        } else if currentTransport == .remote, policy.remoteFallback {
            let devices = await scanDevices()
            if let best = bestLANDevice(from: devices) {
                do {
                    try await migrateToLAN(best)
                } catch {
                    _log("LAN migration failed: \(error)")
                }
            }
        }
    }

    private func bestLANDevice(from devices: [LANDevice]) -> LANDevice? {
        devices
            .filter { $0.usesTLS }
            .filter { !$0.fingerprint.isEmpty }
            .sorted { $0.fingerprint.count > $1.fingerprint.count }
            .first
    }
}

// MARK: - ConnectivityPolicy

public struct ConnectivityPolicy: Sendable {
    public static let `default` = ConnectivityPolicy()

    public var preferredMode: ConnectionMode = .auto
    public var lanPreferred: Bool = true
    public var remoteFallback: Bool = true
    public var autoReconnect: Bool = true
    public var reconnectDelay: TimeInterval = 5.0
    public var heartbeatInterval: TimeInterval = 15.0
    public var maxReconnectAttempts: Int = 5

    public enum ConnectionMode: String, Sendable {
        case auto
        case lanOnly
        case remoteOnly
    }
}

// MARK: - ConnectivityError

public enum ConnectivityError: LocalizedError, Sendable, Equatable {
    case noDevicesAvailable
    case alreadyConnecting
    case tlsHandshakeFailed(String)
    case certificateMismatch
    case authFailed(String)
    case invalidMigration(String)
    case transportError(String)
    case remoteConnectionFailed

    public var errorDescription: String? {
        switch self {
        case .noDevicesAvailable:
            return "Не удалось найти устройства в локальной сети."
        case .alreadyConnecting:
            return "Подключение уже выполняется."
        case let .tlsHandshakeFailed(msg):
            return "Ошибка TLS-соединения: \(msg)"
        case .certificateMismatch:
            return "Сертификат устройства не совпадает с ожидаемым."
        case let .authFailed(msg):
            return "Ошибка аутентификации: \(msg)"
        case let .invalidMigration(msg):
            return "Невозможно выполнить миграцию: \(msg)"
        case let .transportError(msg):
            return "Ошибка транспорта: \(msg)"
        case .remoteConnectionFailed:
            return "Не удалось подключиться через удалённый сервер."
        }
    }
}

// MARK: - Internal

@_disfavoredOverload
private func _log(_ message: String) {
    #if DEBUG
    print("[ConnectivityManager] \(message)")
    #endif
}
