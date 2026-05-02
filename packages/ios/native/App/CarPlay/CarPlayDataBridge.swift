import CarPlay
import Foundation

struct CarPlayTrackSnapshot: Codable {
    let id: String
    let title: String
    let subtitle: String?
    let artist: String?
    let album: String?
    let artworkUrl: String?
}

struct CarPlayCollectionSnapshot: Codable {
    let id: String
    let title: String
    let subtitle: String?
    let tracks: [CarPlayTrackSnapshot]
}

struct CarPlayLibraryBucketSnapshot: Codable {
    let id: String
    let title: String
    let tracks: [CarPlayTrackSnapshot]?
    let collections: [CarPlayCollectionSnapshot]?
}

struct CarPlayPlaylistSnapshot: Codable {
    let id: String
    let title: String
    let subtitle: String?
    let tracks: [CarPlayTrackSnapshot]
}

struct CarPlayNowPlayingSnapshot: Codable {
    let trackId: String
    let title: String
    let artist: String
    let album: String
    let artworkUrl: String?
    let isPlaying: Bool
    let isFavorite: Bool
}

struct CarPlayTemplateState {
    let favorites: [CarPlayTrackSnapshot]
    let libraryBuckets: [CarPlayLibraryBucketSnapshot]
    let playlists: [CarPlayPlaylistSnapshot]
    let nowPlaying: CarPlayNowPlayingSnapshot?
}

final class CarPlayDataBridge {
    static let shared = CarPlayDataBridge()

    private init() {}

    private weak var interfaceController: CPInterfaceController?
    private var eventSink: ((String, [String: Any]) -> Void)?

    private(set) var favorites: [CarPlayTrackSnapshot] = []
    private(set) var libraryBuckets: [CarPlayLibraryBucketSnapshot] = []
    private(set) var playlists: [CarPlayPlaylistSnapshot] = []
    private(set) var nowPlaying: CarPlayNowPlayingSnapshot?

    func setEventSink(_ sink: @escaping (String, [String: Any]) -> Void) {
        eventSink = sink
    }

    func attachInterfaceController(_ controller: CPInterfaceController) {
        NSLog("[CarPlay] attach controller")
        interfaceController = controller
        refreshRootTemplate(animated: false)
        NSLog("[CarPlay] initial empty root rendered")
        eventSink?("carPlayConnected", [:])
        NSLog("[CarPlay] sent carPlayConnected eventSink=%@", eventSink == nil ? "nil" : "set")
    }

    func detachInterfaceController(_ controller: CPInterfaceController) {
        NSLog("[CarPlay] detach controller")
        if interfaceController === controller {
            interfaceController = nil
        }
    }

    func updateLibrary(from json: String) throws {
        NSLog("[CarPlay] updateLibrary bytes=%d", json.utf8.count)
        let data = Data(json.utf8)
        libraryBuckets = try JSONDecoder().decode([CarPlayLibraryBucketSnapshot].self, from: data)
        NSLog("[CarPlay] updateLibrary decoded buckets=%d", libraryBuckets.count)
        refreshRootTemplate()
    }

    func updateFavorites(from json: String) throws {
        NSLog("[CarPlay] updateFavorites bytes=%d", json.utf8.count)
        let data = Data(json.utf8)
        favorites = try JSONDecoder().decode([CarPlayTrackSnapshot].self, from: data)
        NSLog("[CarPlay] updateFavorites decoded count=%d", favorites.count)
        refreshRootTemplate()
    }

    func updatePlaylists(from json: String) throws {
        NSLog("[CarPlay] updatePlaylists bytes=%d", json.utf8.count)
        let data = Data(json.utf8)
        playlists = try JSONDecoder().decode([CarPlayPlaylistSnapshot].self, from: data)
        NSLog("[CarPlay] updatePlaylists decoded count=%d", playlists.count)
        refreshRootTemplate()
    }

    func updateNowPlaying(from json: String?) throws {
        guard let json, !json.isEmpty else {
            NSLog("[CarPlay] updateNowPlaying cleared")
            nowPlaying = nil
            return
        }

        let data = Data(json.utf8)
        nowPlaying = try JSONDecoder().decode(CarPlayNowPlayingSnapshot.self, from: data)
        NSLog("[CarPlay] updateNowPlaying set trackId=%@", nowPlaying?.trackId ?? "nil")
    }

    func clearState() {
        NSLog("[CarPlay] clearState called")
        favorites = []
        libraryBuckets = []
        playlists = []
        nowPlaying = nil
        refreshRootTemplate()
    }

    func showNowPlaying() {
        interfaceController?.pushTemplate(CPNowPlayingTemplate.shared, animated: true, completion: nil)
    }

    private func refreshRootTemplate(animated: Bool = true) {
        guard let controller = interfaceController else {
            NSLog("[CarPlay] refreshRoot skipped: no controller")
            return
        }

        let actions = RootTemplateBuilder.Actions(
            pushTemplate: { [weak self] template in
                self?.interfaceController?.pushTemplate(template, animated: true, completion: nil)
            },
            showNowPlaying: { [weak self] in
                self?.showNowPlaying()
            },
            onFavoriteTrackSelected: { [weak self] track in
                self?.eventSink?("carPlaySelectFavoriteTrack", ["trackId": track.id])
            },
            onLibraryBucketSelected: { [weak self] bucket in
                self?.emitLibrarySelection(
                    bucketId: bucket.id,
                    selectionType: "bucket",
                    itemId: bucket.id,
                    parentId: nil
                )
            },
            onLibraryCollectionSelected: { [weak self] bucketId, collection in
                self?.emitLibrarySelection(
                    bucketId: bucketId,
                    selectionType: "collection",
                    itemId: collection.id,
                    parentId: nil
                )
            },
            onLibraryTrackSelected: { [weak self] bucketId, parentId, track in
                self?.emitLibrarySelection(
                    bucketId: bucketId,
                    selectionType: "track",
                    itemId: track.id,
                    parentId: parentId
                )
            },
            onPlaylistSelected: { [weak self] playlist in
                self?.eventSink?("carPlaySelectPlaylist", ["playlistId": playlist.id])
            },
            onPlaylistTrackSelected: { [weak self] playlistId, track in
                self?.eventSink?("carPlaySelectPlaylistTrack", [
                    "playlistId": playlistId,
                    "trackId": track.id,
                ])
            }
        )

        let root = RootTemplateBuilder.buildRootTemplate(
            state: CarPlayTemplateState(
                favorites: favorites,
                libraryBuckets: libraryBuckets,
                playlists: playlists,
                nowPlaying: nowPlaying
            ),
            actions: actions
        )
        controller.setRootTemplate(root, animated: animated, completion: nil)
        NSLog("[CarPlay] setRoot favs=%d buckets=%d playlists=%d", favorites.count, libraryBuckets.count, playlists.count)
    }

    private func emitLibrarySelection(
        bucketId: String,
        selectionType: String,
        itemId: String,
        parentId: String?
    ) {
        var data: [String: Any] = [
            "bucketId": bucketId,
            "selectionType": selectionType,
            "itemId": itemId,
        ]
        if let parentId {
            data["parentId"] = parentId
        }
        eventSink?("carPlaySelectLibraryItem", data)
    }
}
