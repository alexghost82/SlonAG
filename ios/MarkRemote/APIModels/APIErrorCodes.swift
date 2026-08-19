import Foundation

/// Structured error codes from `server/schemas.py`.
public enum APIErrorCode: String, Codable, Sendable, Equatable {
    case ok
    case invalidRequest = "invalid_request"
    case missingField = "missing_field"
    case invalidType = "invalid_type"
    case unauthorized
    case notFound = "not_found"
    case approvalRequired = "approval_required"
    case idempotencyConflict = "idempotency_conflict"
}
