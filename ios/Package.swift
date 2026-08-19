// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "MarkRemote",
    defaultLocalization: "ru",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        .library(name: "DesignSystem", targets: ["DesignSystem"]),
        .library(name: "MarkRemoteModels", targets: ["MarkRemoteModels"]),
        .library(name: "MarkRemoteSecurity", targets: ["MarkRemoteSecurity"]),
        .library(name: "MarkRemoteNetworking", targets: ["MarkRemoteNetworking"]),
        .library(name: "MarkRemoteFeatures", targets: ["MarkRemoteFeatures", "MarkRemoteApp"]),
        .library(name: "MarkRemoteApp", targets: ["MarkRemoteApp"]),
    ],
    dependencies: [
        .package(
            url: "https://github.com/appwrite/sdk-for-apple.git",
            from: "18.3.0"
        ),
    ],
    targets: [
        .target(
            name: "DesignSystem",
            path: "MarkRemote/DesignSystem"
        ),
        .target(
            name: "MarkRemoteModels",
            path: "MarkRemote/APIModels"
        ),
        .target(
            name: "MarkRemoteSecurity",
            dependencies: ["MarkRemoteModels"],
            path: "MarkRemote/Security"
        ),
        .target(
            name: "MarkRemoteNetworking",
            dependencies: ["MarkRemoteModels", "MarkRemoteSecurity"],
            path: "MarkRemote/Networking"
        ),
        .target(
            name: "MarkRemoteFeatures",
            dependencies: [
                "DesignSystem",
                "MarkRemoteModels",
                "MarkRemoteNetworking",
                "MarkRemoteSecurity",
            ],
            path: "MarkRemote/Features"
        ),
        .target(
            name: "MarkRemoteApp",
            dependencies: [
                "DesignSystem",
                "MarkRemoteModels",
                "MarkRemoteSecurity",
                "MarkRemoteFeatures",
                "MarkRemoteNetworking",
                .product(name: "Appwrite", package: "sdk-for-apple"),
            ],
            path: "MarkRemote/App",
            resources: [.process("Resources")]
        ),
        .testTarget(
            name: "DesignSystemTests",
            dependencies: ["DesignSystem"],
            path: "Tests/DesignSystemTests"
        ),
        .testTarget(
            name: "MarkRemoteNetworkingTests",
            dependencies: ["MarkRemoteNetworking", "MarkRemoteModels", "MarkRemoteSecurity"],
            path: "Tests/MarkRemoteNetworkingTests"
        ),
        .testTarget(
            name: "MarkRemoteFeaturesTests",
            dependencies: ["MarkRemoteFeatures", "DesignSystem", "MarkRemoteModels"],
            path: "Tests/MarkRemoteFeaturesTests"
        ),
        .testTarget(
            name: "MarkRemoteAppTests",
            dependencies: ["MarkRemoteApp"],
            path: "Tests/MarkRemoteAppTests"
        ),
    ]
)
