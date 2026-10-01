// Familiar Server: the Familiar server as a Mac menu-bar app (ADR-0131, ADR-0135, ADR-0136, ADR-0138).
import FamiliarServerCore
import ServiceManagement
import Sparkle
import SwiftUI

@main
struct FamiliarServerApp: App {
    @StateObject private var controller = ServerController()
    /// Updates (ADR-0135 point 3), started only for a release build (`UpdatePolicy`).
    private let updates = SPUStandardUpdaterController(
        startingUpdater: UpdatePolicy.checksForUpdates(
            version: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        ),
        updaterDelegate: nil, userDriverDelegate: nil
    )

    var body: some Scene {
        MenuBarExtra {
            ServerMenu(controller: controller, updates: updates)
        } label: {
            Image(systemName: controller.pauseReason == nil ? "music.note.house" : "music.note.house.fill")
        }
        .menuBarExtraStyle(.menu)
    }
}

struct ServerMenu: View {
    @ObservedObject var controller: ServerController
    let updates: SPUStandardUpdaterController
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled

    var body: some View {
        Text(statusLine)
        if let reason = controller.pauseReason {
            Text("Analysis paused: \(reason)")
        }
        if let folder = controller.musicFolder {
            Text("Music: \(folder.lastPathComponent)")
        }
        Divider()

        switch controller.status {
        case .needsFolder:
            Button("Choose Music Folder…") { controller.chooseFolder() }
            Divider()
            // ADR-0135 point 5: the first run says where the player is, since the server plays nothing.
            playerLinks
        case .needsApproval:
            Button("Allow in System Settings…") { controller.openLoginItemsSettings() }
            Button("Try Again") { controller.start() }
        case .failed:
            Button("Try Again") { controller.start() }
        default:
            playerLinks
            Button("Pair a Phone…") { controller.openAdmin(path: "server/access") }
            Button("Open Admin") { controller.openAdmin() }
            Toggle("Allow Phones to Connect", isOn: $controller.lanEnabled)
            Divider()
            if controller.pausedByOwner {
                Button("Resume Analysis") { controller.setPausedByOwner(false) }
            } else {
                Button("Pause Analysis") { controller.setPausedByOwner(true) }
                if controller.pauseReason != nil {
                    Button("Analyse Anyway for an Hour") { controller.analyseAnywayForAnHour() }
                }
            }
            Button("Change Music Folder…") { controller.chooseFolder() }
        }

        Divider()
        if updates.updater.sessionInProgress == false, UpdatePolicy.checksForUpdates(version: version) {
            Button("Check for Updates…") { updates.checkForUpdates(nil) }
        }
        Toggle("Start at Login", isOn: $launchAtLogin)
            .onChange(of: launchAtLogin) { _, enabled in
                do {
                    if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                } catch {
                    launchAtLogin = SMAppService.mainApp.status == .enabled
                }
            }
        Button("Quit Familiar Server") { controller.quit() }
    }

    private var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
    }

    /// Open the player when one is installed; otherwise, where to get it. Never a button that does
    /// nothing because its destination is not there.
    @ViewBuilder private var playerLinks: some View {
        if controller.status == .running && controller.playerInstalled {
            Button("Open in Familiar") { controller.openInFamiliar() }
        } else if !controller.playerInstalled {
            Button("Get Familiar for Mac…") { controller.getPlayer(for: .mac) }
        }
        Button("Get Familiar for iPhone…") { controller.getPlayer(for: .iPhone) }
    }

    private var statusLine: String {
        switch controller.status {
        case .needsFolder: "Choose your music folder to begin"
        case .needsApproval: "Allow Familiar Server's database in Login Items"
        case .starting(let message): message
        case .running: "Running"
        case .restarting(let delay): "Restarting in \(Int(delay))s…"
        case .failed(let message): message
        }
    }
}
