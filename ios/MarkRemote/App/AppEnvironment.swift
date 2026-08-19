import Foundation
import MarkRemoteNetworking
import MarkRemoteSecurity
import Observation

@MainActor
@Observable
public final class AppEnvironment {
    private enum DefaultsKey {
        static let host = "mark.desktop.host"
        static let port = "mark.desktop.port"
        static let useTLS = "mark.desktop.tls"
        static let certificateFingerprint = "mark.desktop.certificate_fingerprint"
    }

    public var host: String {
        didSet { defaults.set(host, forKey: DefaultsKey.host); rebuild() }
    }

    public var port: Int {
        didSet { defaults.set(port, forKey: DefaultsKey.port); rebuild() }
    }

    public var useTLS: Bool {
        didSet { defaults.set(useTLS, forKey: DefaultsKey.useTLS); rebuild() }
    }

    public var certificateFingerprint: String {
        didSet {
            defaults.set(certificateFingerprint, forKey: DefaultsKey.certificateFingerprint)
            rebuild()
        }
    }

    public private(set) var clientError: String?
    public private(set) var client: DesktopAPIClient?
    public private(set) var eventsClient: (any EventsClient)?
    public private(set) var tokenProvider: DeviceTokenProvider?

    public let credentialStore: any CredentialStore

    private let defaults: UserDefaults
    private var session: URLSession
    private var pinningDelegate: CertificatePinningDelegate?

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        host = defaults.string(forKey: DefaultsKey.host) ?? "127.0.0.1"
        let savedPort = defaults.integer(forKey: DefaultsKey.port)
        port = savedPort == 0 ? 8765 : savedPort
        useTLS = defaults.bool(forKey: DefaultsKey.useTLS)
        certificateFingerprint =
            defaults.string(forKey: DefaultsKey.certificateFingerprint) ?? ""
        credentialStore = KeychainCredentialStore()
        session = URLSession(configuration: .ephemeral)
        rebuild()
    }

    public var baseURLDescription: String {
        "\(useTLS ? "https" : "http")://\(host):\(port)/v1"
    }

    public func rebuild() {
        clientError = nil
        if !useTLS && !Self.isLoopback(host) {
            invalidateClient(
                message: "Подключение к Mac в локальной сети разрешено только по TLS."
            )
            return
        }
        guard var components = URLComponents(string: "\(useTLS ? "https" : "http")://\(host)") else {
            invalidateClient(message: "Некорректный адрес хоста.")
            return
        }
        components.port = port
        guard let url = components.url else {
            invalidateClient(message: "Некорректный адрес хоста.")
            return
        }
        if useTLS {
            let normalized = certificateFingerprint.filter(\.isHexDigit)
            guard normalized.count == 64 else {
                invalidateClient(
                    message: "Для TLS укажите SHA-256 fingerprint сертификата Mac."
                )
                return
            }
            let delegate = CertificatePinningDelegate(
                expectedFingerprint: certificateFingerprint
            )
            pinningDelegate = delegate
            session = URLSession(
                configuration: .ephemeral,
                delegate: delegate,
                delegateQueue: nil
            )
        } else {
            pinningDelegate = nil
            session = URLSession(configuration: .ephemeral)
        }

        let provider = DeviceTokenProvider(
            baseURL: url,
            credentialStore: credentialStore,
            session: session
        )
        do {
            client = try DesktopAPIClient(
                baseURL: url,
                allowNonLoopback: true,
                session: session,
                tokenProvider: provider
            )
            eventsClient = URLSessionEventsClient(
                baseURL: url,
                session: session,
                tokenProvider: provider
            )
            tokenProvider = provider
        } catch {
            invalidateClient(message: "Не удалось настроить соединение: \(error)")
        }
    }

    public func forgetTokens() {
        tokenProvider?.invalidate()
    }

    private func invalidateClient(message: String) {
        client = nil
        eventsClient = nil
        tokenProvider = nil
        clientError = message
    }

    private static func isLoopback(_ host: String) -> Bool {
        let normalized = host
            .trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
            .lowercased()
        return normalized == "localhost"
            || normalized == "127.0.0.1"
            || normalized == "::1"
    }
}
