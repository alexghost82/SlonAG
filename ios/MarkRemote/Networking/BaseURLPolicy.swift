import Foundation

public enum BaseURLPolicyError: Error, Sendable, Equatable {
    case emptyHost
    case forbiddenHost(String)
    case nonLoopbackHost(String)
    case invalidURL
}

/// Loopback-first base URL construction for Desktop Control API.
public enum BaseURLPolicy {
    public static let defaultPort: Int = 8765
    public static let defaultHost: String = "127.0.0.1"

    private static let forbiddenHosts: Set<String> = [
        "0.0.0.0",
        "::",
        "[::]",
    ]

    private static let loopbackNames: Set<String> = [
        "localhost",
        "localhost.localdomain",
    ]

    public static func makeBaseURL(
        host: String = defaultHost,
        port: Int = defaultPort,
        scheme: String = "http",
        allowNonLoopback: Bool = false
    ) throws -> URL {
        let trimmed = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw BaseURLPolicyError.emptyHost
        }

        let normalized = normalizeHost(trimmed)
        if forbiddenHosts.contains(normalized) {
            throw BaseURLPolicyError.forbiddenHost(trimmed)
        }
        if !isLoopbackHost(normalized), !allowNonLoopback {
            throw BaseURLPolicyError.nonLoopbackHost(trimmed)
        }

        var components = URLComponents()
        components.scheme = scheme
        components.host = trimmed.hasPrefix("[") ? String(trimmed.dropFirst().dropLast()) : trimmed
        components.port = port
        guard let url = components.url else {
            throw BaseURLPolicyError.invalidURL
        }
        return url
    }

    public static func validate(baseURL: URL, allowNonLoopback: Bool = false) throws {
        guard let host = baseURL.host, !host.isEmpty else {
            throw BaseURLPolicyError.emptyHost
        }
        let normalized = normalizeHost(host)
        if forbiddenHosts.contains(normalized) {
            throw BaseURLPolicyError.forbiddenHost(host)
        }
        if !isLoopbackHost(normalized), !allowNonLoopback {
            throw BaseURLPolicyError.nonLoopbackHost(host)
        }
    }

    public static func isLoopbackHost(_ host: String) -> Bool {
        let normalized = normalizeHost(host)
        if loopbackNames.contains(normalized) {
            return true
        }
        if let ipv4 = IPv4Address(normalized), ipv4.isLoopback {
            return true
        }
        if let ipv6 = IPv6Address(normalized), ipv6.isLoopback {
            return true
        }
        return false
    }

    private static func normalizeHost(_ host: String) -> String {
        var value = host.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if value.hasPrefix("["), value.hasSuffix("]") {
            value = String(value.dropFirst().dropLast())
        }
        while value.hasSuffix(".") {
            value = String(value.dropLast())
        }
        return value
    }
}

private struct IPv4Address {
    let isLoopback: Bool

    init?(_ string: String) {
        let parts = string.split(separator: ".")
        guard parts.count == 4 else { return nil }
        var octets: [UInt8] = []
        for part in parts {
            guard let value = UInt8(part) else { return nil }
            octets.append(value)
        }
        isLoopback = octets[0] == 127
    }
}

private struct IPv6Address {
    let isLoopback: Bool

    init?(_ string: String) {
        // Accept common loopback forms without full IPv6 parsing.
        let normalized = string.lowercased()
        if normalized == "::1" || normalized == "0:0:0:0:0:0:0:1" {
            isLoopback = true
            return
        }
        // Reject unspecified / other forms as non-loopback for policy purposes.
        if normalized == "::" || normalized == "0:0:0:0:0:0:0:0" {
            isLoopback = false
            return
        }
        return nil
    }
}
