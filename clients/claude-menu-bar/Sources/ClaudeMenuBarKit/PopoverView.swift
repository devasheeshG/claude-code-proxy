import AppKit
import SwiftUI

public struct PopoverView: View {
    @ObservedObject var model: DashboardModel
    @State private var showingSettings = false

    public init(model: DashboardModel) { self.model = model }

    public var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "sparkles.fill").font(.title2).foregroundStyle(.orange)
                VStack(alignment: .leading, spacing: 2) { Text("Claude Code Proxy").font(.headline); Text("Menu bar dashboard").font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Button { showingSettings = true } label: { Image(systemName: "gearshape").font(.body) }.buttonStyle(.borderless).help("Connection settings")
                Label(model.isConfigured ? "Configured" : "Not configured", systemImage: model.isConfigured ? "checkmark.circle" : "circle.dashed").font(.caption).foregroundStyle(model.isConfigured ? .green : .secondary)
            }.padding(.horizontal, 14).padding(.top, 14)

            Picker("View", selection: $model.tab) {
                ForEach(DashboardModel.Tab.allCases, id: \.self) { Text($0.rawValue).tag($0) }
            }.pickerStyle(.segmented).padding(.horizontal, 14).padding(.top, 11)

            ScrollView {
                switch model.tab {
                case .overview: OverviewView(model: model)
                case .accounts: AccountsView(model: model)
                }
            }.padding(14).scrollIndicators(.hidden)

            Divider()
            HStack {
                Text("Updated ") + Text(model.lastUpdated, style: .relative) + Text(" ago")
                Spacer()
                Text("Open dashboard").foregroundStyle(.orange)
                Button { NSApplication.shared.terminate(nil) } label: {
                    Label("Quit", systemImage: "power")
                }
                .buttonStyle(.borderless)
                .font(.caption)
                .foregroundStyle(.secondary)
                .help("Quit Claude Code Proxy")
            }.font(.caption2).foregroundStyle(.secondary).padding(10)
        }.background(.regularMaterial).sheet(isPresented: $showingSettings) { ConnectionSettings(model: model) }
    }
}

private struct ConnectionSettings: View {
    @ObservedObject var model: DashboardModel
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Connection").font(.title3.bold())
            Text("Connect this menu-bar app to any compatible proxy. Values are stored locally; the secret is kept in the macOS Keychain.").font(.caption).foregroundStyle(.secondary)
            TextField("Base URL", text: $model.baseURL).textFieldStyle(.roundedBorder)
            TextField("Username (optional)", text: $model.username).textFieldStyle(.roundedBorder)
            SecureField("API key or password", text: $model.secret).textFieldStyle(.roundedBorder)
            HStack { Spacer(); Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction); Button("Save") { model.saveConnection(); dismiss() }.buttonStyle(.borderedProminent).tint(.orange).keyboardShortcut(.defaultAction) }
        }.padding(20).frame(width: 380)
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
            Text("POOL WINDOWS").font(.caption2).foregroundStyle(.secondary)
            HStack(spacing: 8) { Quota(title: "5-hour average", value: 41); Quota(title: "Weekly average", value: 52) }
            Button { model.tab = .accounts } label: { Label("Open Accounts", systemImage: "person.2") }
                .buttonStyle(.borderedProminent).tint(.orange)
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
            Text("12 accounts · 8 usable · 2 re-auth · 2 cooling").font(.caption).foregroundStyle(.secondary)
            Picker("Filter", selection: $filter) { ForEach(["All", "Authenticated", "Usable"], id: \.self) { Text($0).tag($0) } }
                .pickerStyle(.segmented).controlSize(.small)
            ForEach(visible) { AccountRow(account: $0) }
            Button { model.refresh() } label: { Label(model.isRefreshing ? "Refreshing…" : "Refresh limits", systemImage: "arrow.clockwise") }
                .buttonStyle(.borderedProminent).tint(.orange).disabled(model.isRefreshing)
        }
    }
}

private struct AccountRow: View {
    let account: DashboardModel.Account
    private var color: Color { switch account.state { case .ready: .green; case .cooling: .orange; case .reauth: .red } }
    private var label: String { switch account.state { case .ready: "Ready"; case .cooling: "Cooling"; case .reauth: "Re-auth" } }
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack { VStack(alignment: .leading, spacing: 2) { Text(account.name).font(.subheadline.bold()); Text(account.email).font(.caption2).foregroundStyle(.secondary) }; Spacer(); Label(label, systemImage: "circle.fill").font(.caption2).foregroundStyle(color) }
            HStack(spacing: 8) { Quota(title: "5-hour", value: account.fiveHour); Quota(title: "Weekly", value: account.weekly) }
        }.padding(10).background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 9)).overlay(RoundedRectangle(cornerRadius: 9).stroke(.quaternary, lineWidth: 1))
    }
}

private struct Metric: View {
    let title: String; let value: String; let detail: String
    var body: some View { VStack(alignment: .leading, spacing: 5) { Text(title.uppercased()).font(.caption2).foregroundStyle(.secondary); Text(value).font(.system(.headline, design: .monospaced).weight(.semibold)); Text(detail).font(.caption2).foregroundStyle(.secondary) }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(.quaternary.opacity(0.32), in: RoundedRectangle(cornerRadius: 9)) }
}

private struct Quota: View {
    let title: String; let value: Int
    var color: Color { value >= 95 ? .red : value >= 80 ? .orange : .green }
    var body: some View { VStack(alignment: .leading, spacing: 5) { HStack { Text(title).font(.caption2); Spacer(); Text("\(value)%").font(.caption2.monospaced()).bold() }; ProgressView(value: Double(value), total: 100).tint(color); Text("rolling").font(.caption2).foregroundStyle(.secondary) }.frame(maxWidth: .infinity, alignment: .leading).padding(9).background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 8)) }
}
