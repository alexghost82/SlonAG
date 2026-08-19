import Foundation

/// Generates opaque idempotency keys for mutating Desktop API requests.
public enum IdempotencyKey {
    /// Returns a new unique key suitable for `idempotencyKey` request fields.
    public static func make() -> String {
        UUID().uuidString
    }
}
