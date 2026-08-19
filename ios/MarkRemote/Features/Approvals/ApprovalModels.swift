import Foundation
import MarkRemoteModels

/// Presentation model for an approval request. Never omit path/URL/args when present.
public struct ApprovalItem: Identifiable, Equatable, Sendable {
    public var id: String
    /// Tool / action name shown to the user.
    public var action: String
    public var riskRaw: String
    public var riskLevel: Int
    public var status: String
    public var source: String?
    /// Exact arguments string (JSON or formatted). Shown in full when present.
    public var exactArguments: String?
    public var path: String?
    public var url: String?
    public var intent: String?

    public init(
        id: String,
        action: String,
        riskRaw: String,
        riskLevel: Int? = nil,
        status: String,
        source: String? = nil,
        exactArguments: String? = nil,
        path: String? = nil,
        url: String? = nil,
        intent: String? = nil
    ) {
        self.id = id
        self.action = action
        self.riskRaw = riskRaw
        self.riskLevel = riskLevel ?? ApprovalRisk.level(from: riskRaw)
        self.status = status
        self.source = source
        self.exactArguments = exactArguments
        self.path = path
        self.url = url
        self.intent = intent
    }

    public init(dto: ApprovalInfo, exactArguments: String? = nil, path: String? = nil, url: String? = nil) {
        self.init(
            id: dto.id,
            action: dto.toolName,
            riskRaw: dto.risk,
            status: dto.status,
            source: dto.source,
            exactArguments: exactArguments,
            path: path,
            url: url,
            intent: dto.intent
        )
    }

    public var requiresBiometricForAllow: Bool {
        riskLevel >= ApprovalRisk.biometricThreshold
    }

    public var riskTitleRU: String {
        ApprovalRisk.titleRU(for: riskLevel)
    }

    public var isPending: Bool {
        let lowered = status.lowercased()
        return lowered == "pending" || lowered == "open" || lowered == "awaiting"
    }
}

public enum ApprovalDecisionKind: String, Sendable, Equatable {
    /// Allow this invocation once (never auto-approve).
    case allowOnce = "allow"
    case deny = "deny"
}

/// Parses Desktop risk strings into numeric levels 0…4.
public enum ApprovalRisk: Sendable {
    public static let biometricThreshold = 3

    public static func level(from raw: String) -> Int {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if let value = Int(trimmed) {
            return min(4, max(0, value))
        }
        switch trimmed {
        case "read", "status", "low", "0":
            return 0
        case "notify", "reversible", "1":
            return 1
        case "confirm", "medium", "2":
            return 2
        case "exact", "exact_confirm", "high", "3":
            return 3
        case "biometric", "reconfirm", "critical", "4":
            return 4
        default:
            if let digit = trimmed.compactMap(\.wholeNumberValue).first {
                return min(4, max(0, digit))
            }
            return 0
        }
    }

    public static func titleRU(for level: Int) -> String {
        switch level {
        case 0: return "0 — чтение"
        case 1: return "1 — уведомление"
        case 2: return "2 — подтверждение"
        case 3: return "3 — точное подтверждение"
        case 4: return "4 — биометрия"
        default: return "\(level)"
        }
    }
}
