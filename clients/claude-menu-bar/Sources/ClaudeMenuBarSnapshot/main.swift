import AppKit
import ClaudeMenuBarKit
import SwiftUI

@MainActor
func render(to destination: URL, accounts: Bool) throws {
    NSApplication.shared.setActivationPolicy(.prohibited)
    let model = DashboardModel()
    if accounts { model.showAccounts() }
    let view = PopoverView(model: model).frame(width: 390, height: 620).environment(\.colorScheme, .dark)
    let hosting = NSHostingView(rootView: view)
    hosting.frame = NSRect(x: 0, y: 0, width: 390, height: 620)
    hosting.layoutSubtreeIfNeeded()
    guard let rep = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else { throw NSError(domain: "snapshot", code: 1) }
    hosting.cacheDisplay(in: hosting.bounds, to: rep)
    guard let png = rep.representation(using: .png, properties: [:]) else { throw NSError(domain: "snapshot", code: 2) }
    try png.write(to: destination)
}

let output = CommandLine.arguments.dropFirst().first ?? "Claude-Code-Proxy-popover.png"
let accounts = CommandLine.arguments.contains("--accounts")
Task { @MainActor in
    do { try render(to: URL(fileURLWithPath: output), accounts: accounts); exit(0) }
    catch { fputs("Snapshot failed: \(error)\n", stderr); exit(1) }
}
RunLoop.main.run()
