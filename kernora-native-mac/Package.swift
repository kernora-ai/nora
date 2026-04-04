// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "KernoraNative",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "kernora-native-mac", targets: ["KernoraNative"])
    ],
    dependencies: [
        .package(url: "https://github.com/ml-explore/mlx-swift-lm.git", from: "2.31.3")
    ],
    targets: [
        .executableTarget(
            name: "KernoraNative",
            dependencies: [
                .product(name: "MLXLLM", package: "mlx-swift-lm")
            ],
            path: "Sources"
        )
    ]
)
