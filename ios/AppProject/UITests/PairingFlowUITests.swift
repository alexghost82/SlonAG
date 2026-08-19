import XCTest

/// End-to-end flow against a live Desktop Control API on 127.0.0.1:8765.
/// Start it first: `python3 -m server --host 127.0.0.1 --port 8765`.
final class PairingFlowUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testPairAndSeeDesktopStatus() throws {
        let app = XCUIApplication()
        app.launch()

        app.tabBars.buttons["Удалённо"].tap()
        let pairingDestination = app.buttons["Сопряжение"]
        XCTAssertTrue(pairingDestination.waitForExistence(timeout: 5))
        pairingDestination.tap()

        let createCode = app.buttons["Создать код"]
        XCTAssertTrue(createCode.waitForExistence(timeout: 5))
        createCode.tap()

        let codeText = app.staticTexts.matching(
            NSPredicate(format: "label BEGINSWITH 'Одноразовый код '")
        ).firstMatch
        XCTAssertTrue(codeText.waitForExistence(timeout: 10), "Сервер не выдал одноразовый код")

        app.buttons["Завершить сопряжение"].tap()

        let pairedDevice = app.staticTexts["Рабочий стол"]
        XCTAssertTrue(pairedDevice.waitForExistence(timeout: 10), "Сопряжение не завершилось")
        attachScreenshot(app, name: "pairing-complete")

        app.tabBars.buttons["Управление"].tap()
        let connected = app.staticTexts["LISTENING"]
        XCTAssertTrue(
            connected.waitForExistence(timeout: 10),
            "Панель не получила статус рабочего стола"
        )
        attachScreenshot(app, name: "dashboard-paired")
    }

    private func attachScreenshot(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
