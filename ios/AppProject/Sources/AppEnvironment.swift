import Foundation
import MarkRemoteNetworking
import MarkRemoteSecurity
import Observation

/// Connection settings + live client wiring for the shipped iOS app.
///
/// Talks only to the Desktop Control API. Never stores AI provider keys:
/// only the per-device pairing credential goes to the Keychain.
@MainActor
@Observable
final class AppEnvironment {
    private enum DefaultsKey {
        static let host = "mark.desktop.host"
        static let port = "mark.desktop.port"
        static let useTLS = "mark.desktop.tls"
    }

    var host: String {
        didSet { defaults.set(host, forKey: DefaultsKey.host); rebuild() }
    }

    var port: Int {
        didSet { defaults.set(port, forKey: DefaultsKey.port); rebuild() }
    }

    var useTLS: Bool {
        didSet { defaults.set(useTLS, forKey: DefaultsKey.useTLS); rebuild() }
    }

    private(set) var clientError: String?

    let credentialStore: any CredentialStore
    private let defaults: UserDefaults
    private let session: URLSession

    private(set) var client: DesktopAPIClient?
    private(set) var tokenProvider: DeviceTokenProvider?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.host = defaults.string(forKey: DefaultsKey.host) ?? "127.0.0.1"
        let storedPort = defaults.integer(forKey: DefaultsKey.port)
        self.port = storedPort == 0 ? 8765 : storedPort
        self.useTLS = defaults.bool(forKey: DefaultsKey.useTLS)
        self.credentialStore = KeychainCredentialStore()
        self.session = URLSession(configuration: .ephemeral)
        rebuild()
    }

    var baseURLDescription: String {
        "\(useTLS ? "https" : "http")://\(host):\(port)/v1"
    }

    /// Rebuilds the API client whenever connection settings change.
    ///
    /// LAN hosts are permitted because same-network use is an approved
    /// deployment; wildcard/public binds stay rejected by `BaseURLPolicy`.
    func rebuild() {
        clientError = nil
        guard var components = URLComponents(string: "\(useTLS ? "https" : "http")://\(host)") else {
            client = nil
            tokenProvider = nil
            clientError = "Некорректный адрес хоста."
            return
        }
        components.port = port
        guard let url = components.url else {
            client = nil
            tokenProvider = nil
            clientError = "Некорректный адрес хоста."
            return
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
            tokenProvider = provider
        } catch {
            client = nil
            tokenProvider = nil
            clientError = "Не удалось подключиться: \(error)"
        }
    }

    func forgetTokens() {
        tokenProvider?.invalidate()
    }
}
