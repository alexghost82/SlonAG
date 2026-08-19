import XCTest
import SwiftUI
@testable import DesignSystem

final class DesignSystemTokenTests: XCTestCase {
    func testSpacingTokens() {
        XCTAssertEqual(MRSpacing.xxxs, 2)
        XCTAssertEqual(MRSpacing.xxs, 4)
        XCTAssertEqual(MRSpacing.xs, 8)
        XCTAssertEqual(MRSpacing.sm, 12)
        XCTAssertEqual(MRSpacing.md, 16)
        XCTAssertEqual(MRSpacing.lg, 24)
        XCTAssertEqual(MRSpacing.xl, 32)
        XCTAssertEqual(MRSpacing.xxl, 48)
    }

    func testCornerRadiusTokens() {
        XCTAssertEqual(MRCornerRadius.sm, 8)
        XCTAssertEqual(MRCornerRadius.md, 12)
        XCTAssertEqual(MRCornerRadius.lg, 16)
        XCTAssertEqual(MRCornerRadius.pill, 999)
    }

    func testSemanticColorsResolve() {
        XCTAssertNotNil(MRColor.background)
        XCTAssertNotNil(MRColor.secondaryBackground)
        XCTAssertNotNil(MRColor.groupedBackground)
        XCTAssertNotNil(MRColor.label)
        XCTAssertNotNil(MRColor.secondaryLabel)
        XCTAssertNotNil(MRColor.tertiaryLabel)
        XCTAssertNotNil(MRColor.separator)
        XCTAssertNotNil(MRColor.accent)
        XCTAssertNotNil(MRColor.success)
        XCTAssertNotNil(MRColor.warning)
        XCTAssertNotNil(MRColor.danger)
        XCTAssertNotNil(MRColor.online)
        XCTAssertNotNil(MRColor.offline)
    }

    func testTypographyHelpersExist() {
        XCTAssertNotNil(MRTypography.largeTitle)
        XCTAssertNotNil(MRTypography.title)
        XCTAssertNotNil(MRTypography.headline)
        XCTAssertNotNil(MRTypography.body)
        XCTAssertNotNil(MRTypography.callout)
        XCTAssertNotNil(MRTypography.subheadline)
        XCTAssertNotNil(MRTypography.footnote)
        XCTAssertNotNil(MRTypography.caption)
        XCTAssertNotNil(MRTypography.caption2)
        XCTAssertNotNil(MRTypography.monospacedDigit(.body))
    }
}

@MainActor
final class DesignSystemComponentTests: XCTestCase {
    func testConnectionStatusRussianLabels() {
        XCTAssertEqual(MRConnectionStatus.online.titleRU, "Онлайн")
        XCTAssertEqual(MRConnectionStatus.offline.titleRU, "Офлайн")
        XCTAssertFalse(MRConnectionStatus.online.systemImage.isEmpty)
        XCTAssertFalse(MRConnectionStatus.offline.systemImage.isEmpty)
    }

    func testPrimaryButtonInstantiates() {
        let view = MRPrimaryButton("Продолжить", systemImage: "play.fill") {}
        XCTAssertNotNil(view.body)
    }

    func testSecondaryButtonInstantiates() {
        let view = MRSecondaryButton("Отмена") {}
        XCTAssertNotNil(view.body)
    }

    func testSectionHeaderInstantiates() {
        let view = MRSectionHeader("Устройства", subtitle: "Локальная сеть")
        XCTAssertNotNil(view.body)
    }

    func testStatusBadgeInstantiates() {
        for status in MRConnectionStatus.allCases {
            let view = MRStatusBadge(status)
            XCTAssertNotNil(view.body)
        }
    }

    func testEmptyStateInstantiates() {
        let view = MREmptyState(
            title: "Пусто",
            message: "Нет данных",
            systemImage: "tray",
            actionTitle: "Обновить",
            action: {}
        )
        XCTAssertNotNil(view.body)
    }
}
