import Foundation

/// Gate for high-risk approvals (Face ID / Touch ID / device passcode).
public protocol BiometricAuthenticating: Sendable {
    func canEvaluate() -> Bool
    func evaluate(reason: String) async throws -> Bool
}

public enum BiometricAuthError: Error, Sendable, Equatable {
    case unavailable
    case failed
    case cancelled
}

#if canImport(LocalAuthentication)
import LocalAuthentication

/// Production LocalAuthentication wrapper.
public final class LocalAuthenticationGate: BiometricAuthenticating, @unchecked Sendable {
    private let policy: LAPolicy

    public init(policy: LAPolicy = .deviceOwnerAuthentication) {
        self.policy = policy
    }

    public func canEvaluate() -> Bool {
        let context = LAContext()
        var error: NSError?
        return context.canEvaluatePolicy(policy, error: &error)
    }

    public func evaluate(reason: String) async throws -> Bool {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(policy, error: &error) else {
            throw BiometricAuthError.unavailable
        }
        do {
            return try await context.evaluatePolicy(policy, localizedReason: reason)
        } catch let laError as LAError where laError.code == .userCancel || laError.code == .appCancel {
            throw BiometricAuthError.cancelled
        } catch {
            throw BiometricAuthError.failed
        }
    }
}
#endif

/// Deterministic mock for tests and previews.
public final class MockBiometricAuthenticator: BiometricAuthenticating, @unchecked Sendable {
    public var isAvailable: Bool
    public var result: Result<Bool, BiometricAuthError>
    public private(set) var evaluateCallCount = 0
    public private(set) var lastReason: String?

    public init(
        isAvailable: Bool = true,
        result: Result<Bool, BiometricAuthError> = .success(true)
    ) {
        self.isAvailable = isAvailable
        self.result = result
    }

    public func canEvaluate() -> Bool {
        isAvailable
    }

    public func evaluate(reason: String) async throws -> Bool {
        evaluateCallCount += 1
        lastReason = reason
        switch result {
        case .success(let value):
            return value
        case .failure(let error):
            throw error
        }
    }
}
