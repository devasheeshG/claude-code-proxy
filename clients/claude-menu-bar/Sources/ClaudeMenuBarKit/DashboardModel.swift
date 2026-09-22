import Combine
import Foundation

@MainActor
public final class DashboardModel: ObservableObject {
    public enum Tab: String, CaseIterable, Hashable {
        case overview = "Overview"
        case accounts = "Accounts"
    }

    public enum AccountState { case ready, cooling, reauth }

    public struct Account: Identifiable {
        public let id = UUID()
        public let name: String
        public let email: String
        public let state: AccountState
        public let authenticated: Bool
        public let usable: Bool
        public let fiveHour: Int
        public let weekly: Int
        public let fiveHourReset: String
        public let weeklyReset: String
    }

    @Published public var tab: Tab = .overview
    @Published public var lastUpdated = Date()
    @Published public var isRefreshing = false

    public init() {}

    public func showAccounts() { tab = .accounts }

    public let accounts: [Account] = [
        Account(name: "Shabbir", email: "jamilakhand.jk@gmail.com", state: .ready, authenticated: true, usable: true, fiveHour: 18, weekly: 42, fiveHourReset: "3h 34m", weeklyReset: "6d 22h"),
        Account(name: "Devasheesh", email: "devasheesh@recallrai.com", state: .ready, authenticated: true, usable: true, fiveHour: 63, weekly: 71, fiveHourReset: "2h 12m", weeklyReset: "4d 17h"),
        Account(name: "Animesh", email: "animesh3720@gmail.com", state: .cooling, authenticated: true, usable: false, fiveHour: 100, weekly: 45, fiveHourReset: "1h 56m", weeklyReset: "2d 17h"),
        Account(name: "Vishal", email: "vishalpachpor06@gmail.com", state: .reauth, authenticated: false, usable: false, fiveHour: 0, weekly: 2, fiveHourReset: "unknown", weeklyReset: "5d 23h"),
    ]

    public func refresh() {
        isRefreshing = true
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            lastUpdated = Date()
            isRefreshing = false
        }
    }
}
