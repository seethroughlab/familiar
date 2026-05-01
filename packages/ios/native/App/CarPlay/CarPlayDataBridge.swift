import Foundation
import Capacitor
import UIKit

/// Represents a piece of metadata for a track displayed in CarPlay.
struct CarPlayTrack: Codable {
    let id: String
    let title: String
    let subtitle: String?
    let artworkUrl: String?
}

/// A collection of tracks, representing a Playlist or Album.
struct CarPlayCollection: Codable {
    let id: String
    let title: String
    let subtitle: String?
    let items: [CarPlayTrack]
}

/// The `CarPlayDataBridge` is the central communication hub between the CarPlay native templates
/// and the Web/Capacitor layer. It listens for events from the `FamiliarAudioPlugin` (and other plugins)
/// and updates the `CPInterfaceController` templates accordingly.
class CarPlayDataBridge {
    static let shared = CarPlayDataBridge()
    
    private init() {}

    private weak var interfaceController: CPInterfaceController?

    // MARK: - State

    private(set) var libraryTracks: [CarPlayTrack] = []
    private(set) var collections: [CarPlayCollection] = []
    private(set) var activeTrack: CarPlayTrack?

    func setInterfaceController(_ controller: CPInterfaceController) {
        self.interfaceController = controller
    }

    // MARK: - Data Ingestion

    /// Updates the library tracks from a JSON string.
    func updateLibrary(tracksJson: String) {
        guard let data = tracksJson.data(using: .utf8) else { return }
        do {
            let newTracks = try JSONDecoder().decode([CarPlayTrack].self, from: data)
            self.libraryTracks = newTracks
            print("CarPlayDataBridge: Library updated with \(newTracks.count) tracks.")
            refreshTemplates()
        } catch {
            print("CarPlayDataBridge: Failed to decode library tracks: \(error)")
        }
    }

    /// Updates the collections from a
    func updateCollections(collectionsJson: String) {
        guard let data = collectionsJson.data(using: .utf8) else { return }
        do {
            let newCollections = try JSONDecoder().decode([CarPlayCollection].self, from: data)
            self.collections = newCollections
            print("CarPlayDataBridge: Collections updated with \(newCollections.count) collections.")
            refreshTemplates()
        } catch {
            print("CarPlayDataBridge: Failed to decode collections: \(error)")
        }
    }

    /// Sets the currently playing track.
    func setActiveTrack(_ track: CarPlayTrack?) {
        self.activeTrack = track
        if let track = track {
            // Present the Now Playing template if a track is active.
            let nowPlayingTemplate = RootTemplateBuilder.makeNowPlayingTemplate(for: track)
            interfaceController?.pushTemplate(nowPlayingTemplate, animated: true)
        }
    }

    // MARK: - Template Management

    /// Updates the root template with new data from the Web layer.
    func refreshTemplates() {
        guard let controller = interfaceController else { return }
        let root = RootTemplateBuilder.buildRootTemplate(library: libraryTracks, collections: collections)
        controller.setRootTemplate(root, animated: true, completion: nil)
    }

    /// Notifies the CarPlay UI that a track has changed.
    func updateNowPlaying(title: String, artist: String, album: String, artworkUrl: String?) {
        print("CarPlayDataBridge: Updating Now Playing -> \(title) by \(artist)")
    }

    /// Called when the Web layer triggers a playlist/library refresh.
    func handleLibraryUpdate() {
        refreshTemplates()
    }
}
