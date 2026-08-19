# MarkRemote (iOS)

Swift 6 package for the Slon remote client. Talks only to the Desktop Control API (loopback / paired LAN). Does not embed AI provider API keys.

## Build / test

Command Line Tools alone cannot resolve XCTest. Use Xcode (beta OK):

```bash
cd ios
export DEVELOPER_DIR=/Users/slon/Downloads/Xcode-beta.app/Contents/Developer
swift test
```

`Package.swift` is owned by the integrator for Wave 10. Feature agents fill directories under `MarkRemote/` and `Tests/` only. Do not commit `.build/`.

## Runnable iOS app

`AppProject/MarkRemote.xcodeproj` is the shippable app target. It consumes this package as a local dependency and wires the live Desktop Control API (pairing, token minting, status, screen capture, live JPEG frames, settings).

```bash
export DEVELOPER_DIR=/Users/slon/Downloads/Xcode-beta.app/Contents/Developer
cd ios/AppProject
xcodebuild -project MarkRemote.xcodeproj -scheme MarkRemote \
  -destination 'id=<simulator-udid>' -derivedDataPath .build-xcode build
xcrun simctl install <simulator-udid> .build-xcode/Build/Products/Debug-iphonesimulator/MarkRemote.app
xcrun simctl launch <simulator-udid> local.mark.remote
```

Default connection target is `http://127.0.0.1:8765`; change host/port/TLS in the app's Настройки tab for same-LAN use.

### End-to-end UI test

`MarkRemoteUITests` pairs against a real desktop listener, so start it first:

```bash
python3 -m server --host 127.0.0.1 --port 8765
xcodebuild test -project MarkRemote.xcodeproj -scheme MarkRemote -destination 'id=<simulator-udid>'
```

