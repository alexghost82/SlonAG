import Foundation
import Network

/// Bonjour/mDNS browser for `_mark-control._tcp` Desktop Control services.
@MainActor
public final class BonjourBrowser: NSObject {
    public struct Service: Equatable, Sendable {
        public var name: String
        public var type: String
        public var domain: String
        public var host: String?
        public var port: Int?
        public var usesTLS: Bool
        public var certificateFingerprint: String?
    }

    public private(set) var services: [Service] = []
    public var onUpdate: (([Service]) -> Void)?

    private var browser: NWBrowser?
    private var resolvers: [String: NWConnection] = [:]
    private let queue = DispatchQueue(label: "mark.bonjour.browser")

    public override init() {
        super.init()
    }

    public func start() {
        stop()
        let descriptor = NWBrowser.Descriptor.bonjour(type: "_mark-control._tcp", domain: nil)
        let browser = NWBrowser(for: descriptor, using: .tcp)
        browser.stateUpdateHandler = { _ in }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in
                guard let self else { return }
                self.services = results.compactMap { result in
                    guard case let .service(name, type, domain, _) = result.endpoint else {
                        return nil
                    }
                    let tls = self.txtValue("tls", metadata: result.metadata) == "1"
                    let fingerprint = self.txtValue(
                        "fingerprint_sha256",
                        metadata: result.metadata
                    )
                    return Service(
                        name: name,
                        type: type,
                        domain: domain,
                        host: nil,
                        port: nil,
                        usesTLS: tls,
                        certificateFingerprint: fingerprint
                    )
                }
                self.onUpdate?(self.services)
                for result in results {
                    self.resolve(result.endpoint)
                }
            }
        }
        browser.start(queue: queue)
        self.browser = browser
    }

    public func stop() {
        browser?.cancel()
        browser = nil
        resolvers.values.forEach { $0.cancel() }
        resolvers.removeAll()
        services = []
    }

    private func resolve(_ endpoint: NWEndpoint) {
        guard case let .service(name, _, _, _) = endpoint else { return }
        guard resolvers[name] == nil else { return }
        let connection = NWConnection(to: endpoint, using: .tcp)
        resolvers[name] = connection
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            guard case .ready = state, let connection else { return }
            guard case let .hostPort(host, port) = connection.currentPath?.remoteEndpoint else {
                return
            }
            Task { @MainActor in
                guard let self,
                      let index = self.services.firstIndex(where: { $0.name == name })
                else { return }
                self.services[index].host = String(describing: host)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
                self.services[index].port = Int(port.rawValue)
                self.onUpdate?(self.services)
                connection.cancel()
                self.resolvers.removeValue(forKey: name)
            }
        }
        connection.start(queue: queue)
    }

    private func txtValue(_ key: String, metadata: NWBrowser.Result.Metadata) -> String? {
        guard case let .bonjour(record) = metadata else { return nil }
        guard let entry = record.getEntry(for: key) else { return nil }
        switch entry {
        case let .string(value):
            return value
        case let .data(value):
            return String(data: value, encoding: .utf8)
        case .none, .empty:
            return nil
        @unknown default:
            return nil
        }
    }
}
