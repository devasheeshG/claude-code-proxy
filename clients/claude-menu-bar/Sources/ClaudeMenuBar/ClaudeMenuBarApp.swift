import ClaudeMenuBarKit
import SwiftUI

@main
struct ClaudeMenuBarApp: App {
    @StateObject private var model = DashboardModel()

    var body: some Scene {
        MenuBarExtra {
            PopoverView(model: model)
                .frame(width: 390)
        } label: {
            Image(systemName: "sparkles")
                .help("Claude Code Proxy")
        }
        .menuBarExtraStyle(.window)
    }
}
