import Combine
import Foundation
import Security

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
    @Published public var baseURL: String
    @Published public var username: String
    @Published public var secret: String

    public init() {
        baseURL = UserDefaults.standard.string(forKey: "proxy.baseURL") ?? ""
        username = UserDefaults.standard.string(forKey: "proxy.username") ?? ""
        secret = SecureStore.read(service: "proxy.credentials") ?? ""
    }

    public var isConfigured: Bool {
        !baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            (!secret.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    public func saveConnection() {
        baseURL = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        username = username.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(baseURL, forKey: "proxy.baseURL")
        UserDefaults.standard.set(username, forKey: "proxy.username")
        SecureStore.write(secret, service: "proxy.credentials")
    }

    public func showAccounts() { tab = .accounts }

    public let accounts: [Account] = [
        Account(name: "Account 01", email: "account01@example.test", state: .ready, authenticated: true, usable: true, fiveHour: 18, weekly: 42, fiveHourReset: "3h 34m", weeklyReset: "6d 22h"),
        Account(name: "Account 02", email: "account02@example.test", state: .ready, authenticated: true, usable: true, fiveHour: 63, weekly: 71, fiveHourReset: "2h 12m", weeklyReset: "4d 17h"),
        Account(name: "Account 03", email: "account03@example.test", state: .cooling, authenticated: true, usable: false, fiveHour: 100, weekly: 45, fiveHourReset: "1h 56m", weeklyReset: "2d 17h"),
        Account(name: "Account 04", email: "account04@example.test", state: .reauth, authenticated: false, usable: false, fiveHour: 0, weekly: 2, fiveHourReset: "unknown", weeklyReset: "5d 23h"),
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

private enum SecureStore {
    static func read(service: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func write(_ value: String, service: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        SecItemDelete(query as CFDictionary)
        SecItemAdd(query.merging([kSecValueData as String: data]) { _, new in new } as CFDictionary, nil)
    }
}
