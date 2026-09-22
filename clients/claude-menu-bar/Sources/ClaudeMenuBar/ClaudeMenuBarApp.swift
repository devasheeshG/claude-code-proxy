import ClaudeMenuBarKit
import SwiftUI

@main
struct ClaudeMenuBarApp: App {
    @StateObject private var model = DashboardModel()

    var body: some Scene {
        MenuBarExtra {
            PopoverView(model: model)
                .frame(
                    width: model.isConfigured ? 720 : 390,
                    height: model.isConfigured ? 640 : 360
                )
                .animation(.easeInOut(duration: 0.22), value: model.isConfigured)
        } label: {
            Image(systemName: "sparkles")
                .help("Claude Code Proxy")
        }
        .menuBarExtraStyle(.window)
    }
}
