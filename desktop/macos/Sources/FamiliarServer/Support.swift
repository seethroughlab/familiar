import AppKit
import CoreServices
import FamiliarServerCore
import Foundation
import IOKit.ps
import Security

/// The music folder the owner chose, held as a read-only security-scoped bookmark (ADR-0136 point 2).
///
/// Familiar Server presents the picker itself: an app-scoped bookmark resolves only in the app that
/// made it, so the player could not hand one over. Read-only is asked for twice, by the entitlement
/// and by the bookmark, so a write would fail even if one of them were ever widened.
@MainActor
enum MusicFolder {
    private static let key = "musicFolderBookmark"

    static func choose() -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Use This Folder"
        panel.message = "Choose the folder that holds your music. Familiar only ever reads it."
        NSApp.activate(ignoringOtherApps: true)
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        if let data = try? url.bookmarkData(
            options: [.withSecurityScope, .securityScopeAllowOnlyReadAccess],
            includingResourceValuesForKeys: nil, relativeTo: nil
        ) {
            UserDefaults.standard.set(data, forKey: key)
        }
        return url
    }

    /// The stored folder, with access started. `nil` if none was chosen or the bookmark is stale.
    static func resolve() -> URL? {
        guard let data = UserDefaults.standard.data(forKey: key) else { return nil }
        var stale = false
        guard let url = try? URL(
            resolvingBookmarkData: data, options: [.withSecurityScope],
            relativeTo: nil, bookmarkDataIsStale: &stale
        ), !stale, url.startAccessingSecurityScopedResource() else { return nil }
        return url
    }
}

/// The server's token, which this app minted (ADR-0134 point 2), in the app's own Keychain.
enum TokenStore {
    private static let service = "com.familiar.server.token"

    static func load() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func save(_ token: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = Data(token.utf8)
        SecItemAdd(add as CFDictionary, nil)
    }
}

/// Reads what ADR-0138 decides on: power source, Low Power Mode, and heat.
@MainActor
final class MachineMonitor {
    private var onChange: (MachineState) -> Void
    private(set) var state = MachineState()
    private var timer: Timer?

    init(onChange: @escaping (MachineState) -> Void) {
        self.onChange = onChange
        let center = NotificationCenter.default
        for name in [ProcessInfo.thermalStateDidChangeNotification, Notification.Name.NSProcessInfoPowerStateDidChange] {
            center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.refresh() }
            }
        }
        // Power source changes have no Foundation notification; a minute's polling is plenty for a
        // decision that pauses background work.
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }
        refresh()
    }

    func update(_ change: (inout MachineState) -> Void) {
        change(&state)
        onChange(state)
    }

    func refresh() {
        update { state in
            state.onBattery = Self.onBattery()
            state.lowPowerMode = ProcessInfo.processInfo.isLowPowerModeEnabled
            state.thermal = switch ProcessInfo.processInfo.thermalState {
            case .nominal: .nominal
            case .fair: .fair
            case .serious: .serious
            case .critical: .critical
            @unknown default: .nominal
            }
        }
    }

    private static func onBattery() -> Bool {
        guard let info = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let type = IOPSGetProvidingPowerSourceType(info)?.takeUnretainedValue() as String?
        else { return false }
        return type == kIOPSBatteryPowerValue
    }
}

/// FSEvents on the music folder, reporting that *something* changed (ADR-0136 point 10).
final class FolderWatch {
    private var stream: FSEventStreamRef?
    private let onChange: @Sendable () -> Void

    init(folder: URL, onChange: @escaping @Sendable () -> Void) {
        self.onChange = onChange
        var context = FSEventStreamContext(
            version: 0, info: Unmanaged.passUnretained(self).toOpaque(),
            retain: nil, release: nil, copyDescription: nil
        )
        let callback: FSEventStreamCallback = { _, info, _, _, _, _ in
            guard let info else { return }
            Unmanaged<FolderWatch>.fromOpaque(info).takeUnretainedValue().onChange()
        }
        stream = FSEventStreamCreate(
            nil, callback, &context, [folder.path] as CFArray,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow), 5.0,
            FSEventStreamCreateFlags(kFSEventStreamCreateFlagNoDefer)
        )
        if let stream {
            FSEventStreamSetDispatchQueue(stream, DispatchQueue.global(qos: .utility))
            FSEventStreamStart(stream)
        }
    }

    deinit {
        if let stream {
            FSEventStreamStop(stream)
            FSEventStreamInvalidate(stream)
            FSEventStreamRelease(stream)
        }
    }
}
