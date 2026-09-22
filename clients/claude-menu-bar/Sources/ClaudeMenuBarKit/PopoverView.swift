import AppKit
import SwiftUI

public struct PopoverView: View {
    @ObservedObject var model: DashboardModel
    @State private var showingSettings = false

    public init(model: DashboardModel) {
        self.model = model
        _showingSettings = State(initialValue: !model.isConfigured)
    }

    public var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "sparkles.fill").font(.title2).foregroundStyle(ProxyTheme.brand)
                VStack(alignment: .leading, spacing: 2) { Text("Claude Code Proxy").font(.headline); Text("Menu bar dashboard").font(.caption).foregroundStyle(ProxyTheme.muted) }
                Spacer()
                Button { showingSettings.toggle() } label: { Image(systemName: showingSettings ? "xmark" : "gearshape").font(.body) }.buttonStyle(.borderless).help(showingSettings ? "Close settings" : "Connection settings")
                Label(model.isConfigured ? "Signed in" : "Sign in", systemImage: model.isConfigured ? "checkmark.circle" : "person.crop.circle").font(.caption).foregroundStyle(model.isConfigured ? ProxyTheme.good : ProxyTheme.muted)
            }.padding(.horizontal, 14).padding(.top, 14)

            if showingSettings {
                ConnectionSettings(model: model) { showingSettings = false }.padding(14)
            } else {
                Picker("View", selection: $model.tab) {
                    ForEach(DashboardModel.Tab.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented).tint(ProxyTheme.brand).padding(.horizontal, 14).padding(.top, 11)

                ScrollView {
                    switch model.tab {
                    case .overview: OverviewView(model: model)
                    case .accounts: AccountsView(model: model)
                    }
                }.padding(14).scrollIndicators(.hidden)
            }

            Divider()
            HStack {
                Text("Updated ") + Text(model.lastUpdated, style: .relative) + Text(" ago")
                Spacer()
                Text("Open dashboard").foregroundStyle(ProxyTheme.brand)
                Button { NSApplication.shared.terminate(nil) } label: {
                    Label("Quit", systemImage: "power")
                }
                .buttonStyle(.borderless)
                .font(.caption)
                .foregroundStyle(ProxyTheme.muted)
                .help("Quit Claude Code Proxy")
            }.font(.caption2).foregroundStyle(ProxyTheme.muted).padding(10)
        }.foregroundStyle(ProxyTheme.primary).background(ProxyTheme.background)
    }
}

private struct ConnectionSettings: View {
    @ObservedObject var model: DashboardModel
    @State private var baseURL: String
    @State private var username: String
    @State private var password: String
    @State private var isSigningIn = false
    @State private var errorMessage: String?
    let onClose: () -> Void

    init(model: DashboardModel, onClose: @escaping () -> Void) {
        self.model = model
        self.onClose = onClose
        _baseURL = State(initialValue: model.baseURL)
        _username = State(initialValue: model.username)
        _password = State(initialValue: model.password)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Sign in to your proxy").font(.title3.bold())
            Text("Enter the same dashboard username and password you use in the browser. Your password is stored in the macOS Keychain.").font(.caption).foregroundStyle(ProxyTheme.muted)
            TextField("Base URL", text: $baseURL).textFieldStyle(.roundedBorder)
            TextField("Username", text: $username).textFieldStyle(.roundedBorder)
            SecureField("Password", text: $password).textFieldStyle(.roundedBorder)
            if let errorMessage { Text(errorMessage).font(.caption).foregroundStyle(ProxyTheme.bad) }
            HStack {
                Spacer()
                if model.isConfigured { Button("Cancel", action: onClose).keyboardShortcut(.cancelAction) }
                Button(isSigningIn ? "Signing in…" : "Sign in") {
                    isSigningIn = true
                    errorMessage = nil
                    Task {
                        do { try await model.authenticate(baseURL: baseURL, username: username, password: password); onClose() }
                        catch { errorMessage = error.localizedDescription }
                        isSigningIn = false
                    }
                }.buttonStyle(.borderedProminent).tint(ProxyTheme.brand).keyboardShortcut(.defaultAction).disabled(isSigningIn)
            }
        }
    }
}

private struct OverviewView: View {
    @ObservedObject var model: DashboardModel
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Metric(title: "Tokens processed", value: "4.80B", detail: "+12.4% this month")
                Metric(title: "Requests", value: "36,840", detail: "1,204 today")
            }
            HStack(spacing: 8) {
                Metric(title: "This month", value: "$1,214.62", detail: "$3,842.10 all-time")
                Metric(title: "Cache hit rate", value: "92.4%", detail: "2.30B cache-read")
            }
            Text("POOL WINDOWS").font(.caption2).foregroundStyle(ProxyTheme.muted)
            HStack(spacing: 8) { Quota(title: "5-hour average", value: 41); Quota(title: "Weekly average", value: 52) }
            Button { model.tab = .accounts } label: { Label("Open Accounts", systemImage: "person.2") }
                .buttonStyle(.borderedProminent).tint(ProxyTheme.brand)
        }
    }
}

private struct AccountsView: View {
    @ObservedObject var model: DashboardModel
    @State private var filter = "All"
    private var visible: [DashboardModel.Account] {
        model.accounts.filter { filter == "All" || (filter == "Authenticated" && $0.authenticated) || (filter == "Usable" && $0.usable) }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Account pool").font(.title3.bold())
            Text("12 accounts · 8 usable · 2 re-auth · 2 cooling").font(.caption).foregroundStyle(ProxyTheme.muted)
            Picker("Filter", selection: $filter) { ForEach(["All", "Authenticated", "Usable"], id: \.self) { Text($0).tag($0) } }
                .pickerStyle(.segmented).tint(ProxyTheme.brand).controlSize(.small)
            ForEach(visible) { AccountRow(account: $0) }
            Button { model.refresh() } label: { Label(model.isRefreshing ? "Refreshing…" : "Refresh limits", systemImage: "arrow.clockwise") }
                .buttonStyle(.borderedProminent).tint(ProxyTheme.brand).disabled(model.isRefreshing)
        }
    }
}

private struct AccountRow: View {
    let account: DashboardModel.Account
    private var color: Color { switch account.state { case .ready: ProxyTheme.good; case .cooling: ProxyTheme.warn; case .reauth: ProxyTheme.bad } }
    private var label: String { switch account.state { case .ready: "Ready"; case .cooling: "Cooling"; case .reauth: "Re-auth" } }
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack { VStack(alignment: .leading, spacing: 2) { Text(account.name).font(.subheadline.bold()); Text(account.email).font(.caption2).foregroundStyle(ProxyTheme.muted) }; Spacer(); Label(label, systemImage: "circle.fill").font(.caption2).foregroundStyle(color) }
            HStack(spacing: 8) { Quota(title: "5-hour", value: account.fiveHour); Quota(title: "Weekly", value: account.weekly) }
        }.padding(10).background(ProxyTheme.card, in: RoundedRectangle(cornerRadius: 9)).overlay(RoundedRectangle(cornerRadius: 9).stroke(ProxyTheme.border, lineWidth: 1))
    }
}

private struct Metric: View {
    let title: String; let value: String; let detail: String
    var body: some View { VStack(alignment: .leading, spacing: 5) { Text(title.uppercased()).font(.caption2).foregroundStyle(ProxyTheme.muted); Text(value).font(.system(.headline, design: .monospaced).weight(.semibold)); Text(detail).font(.caption2).foregroundStyle(ProxyTheme.muted) }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(ProxyTheme.card, in: RoundedRectangle(cornerRadius: 9)) }
}

private struct Quota: View {
    let title: String; let value: Int
    var color: Color { value >= 95 ? ProxyTheme.bad : value >= 80 ? ProxyTheme.warn : ProxyTheme.good }
    var body: some View { VStack(alignment: .leading, spacing: 5) { HStack { Text(title).font(.caption2); Spacer(); Text("\(value)%").font(.caption2.monospaced()).bold() }; ProgressView(value: Double(value), total: 100).tint(color); Text("rolling").font(.caption2).foregroundStyle(ProxyTheme.muted) }.frame(maxWidth: .infinity, alignment: .leading).padding(9).background(ProxyTheme.panel, in: RoundedRectangle(cornerRadius: 8)) }
}

private enum ProxyTheme {
    static let background = Color(red: 25/255, green: 25/255, blue: 23/255)
    static let panel = Color(red: 31/255, green: 30/255, blue: 28/255)
    static let card = Color(red: 38/255, green: 37/255, blue: 34/255)
    static let border = Color(red: 59/255, green: 58/255, blue: 53/255)
    static let primary = Color(red: 243/255, green: 241/255, blue: 234/255)
    static let muted = Color(red: 154/255, green: 150/255, blue: 140/255)
    static let brand = Color(red: 217/255, green: 119/255, blue: 87/255)
    static let good = Color(red: 76/255, green: 177/255, blue: 133/255)
    static let warn = Color(red: 224/255, green: 165/255, blue: 90/255)
    static let bad = Color(red: 233/255, green: 130/255, blue: 121/255)
}
