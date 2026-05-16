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

    // Snapshot state — written by the JS sync calls, read by template builders
    private(set) var favorites: [CarPlayTrackSnapshot] = []
    private(set) var libraryBuckets: [CarPlayLibraryBucketSnapshot] = []
    private(set) var playlists: [CarPlayPlaylistSnapshot] = []
    private(set) var nowPlaying: CarPlayNowPlayingSnapshot?

    // Root templates — created once in attachInterfaceController, mutated in-place via updateSections
    private var favoritesTemplate: CPListTemplate?
    private var libraryTemplate: CPListTemplate?
    private var playlistsTemplate: CPListTemplate?
    private var rootActions: RootTemplateBuilder.Actions?

    func setEventSink(_ sink: @escaping (String, [String: Any]) -> Void) {
        eventSink = sink
    }

    func attachInterfaceController(_ controller: CPInterfaceController) {
        NSLog("[CarPlay] attach controller")
        interfaceController = controller

        let actions = makeActions()
        rootActions = actions

        let root = RootTemplateBuilder.buildRootTemplate(
            state: CarPlayTemplateState(
                favorites: favorites,
                libraryBuckets: libraryBuckets,
                playlists: playlists,
                nowPlaying: nowPlaying
            ),
            actions: actions
        )
        favoritesTemplate = root.favorites
        libraryTemplate = root.library
        playlistsTemplate = root.playlists

        controller.setRootTemplate(root.tabBar, animated: false, completion: nil)
        NSLog("[CarPlay] setRoot once favs=%d buckets=%d playlists=%d", favorites.count, libraryBuckets.count, playlists.count)
        NSLog("[CarPlay] initial empty root rendered")
        eventSink?("carPlayConnected", [:])
        NSLog("[CarPlay] sent carPlayConnected eventSink=%@", eventSink == nil ? "nil" : "set")
    }

    func detachInterfaceController(_ controller: CPInterfaceController) {
        NSLog("[CarPlay] detach controller")
        if interfaceController === controller {
            interfaceController = nil
            favoritesTemplate = nil
            libraryTemplate = nil
            playlistsTemplate = nil
            rootActions = nil
        }
    }

    func updateLibrary(from json: String) throws {
        NSLog("[CarPlay] updateLibrary bytes=%d", json.utf8.count)
        let data = Data(json.utf8)
        libraryBuckets = try JSONDecoder().decode([CarPlayLibraryBucketSnapshot].self, from: data)
        NSLog("[CarPlay] updateLibrary decoded buckets=%d", libraryBuckets.count)
        updateLibraryTemplate()
    }

    func updateFavorites(from json: String) throws {
        NSLog("[CarPlay] updateFavorites bytes=%d", json.utf8.count)
        let data = Data(json.utf8)
        favorites = try JSONDecoder().decode([CarPlayTrackSnapshot].self, from: data)
        NSLog("[CarPlay] updateFavorites decoded count=%d", favorites.count)
        updateFavoritesTemplate()
    }

    func updatePlaylists(from json: String) throws {
        NSLog("[CarPlay] updatePlaylists bytes=%d", json.utf8.count)
        let data = Data(json.utf8)
        playlists = try JSONDecoder().decode([CarPlayPlaylistSnapshot].self, from: data)
        NSLog("[CarPlay] updatePlaylists decoded count=%d", playlists.count)
        updatePlaylistsTemplate()
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
        updateFavoritesTemplate()
        updateLibraryTemplate()
        updatePlaylistsTemplate()
    }

    func showNowPlaying() {
        interfaceController?.pushTemplate(CPNowPlayingTemplate.shared, animated: true, completion: nil)
    }

    // MARK: - Private

    private func makeActions() -> RootTemplateBuilder.Actions {
        RootTemplateBuilder.Actions(
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
    }

    private func updateFavoritesTemplate() {
        guard let template = favoritesTemplate, let actions = rootActions else {
            NSLog("[CarPlay] updateFavoritesTemplate skipped: no template")
            return
        }
        let sections = RootTemplateBuilder.makeFavoritesSections(favorites: favorites, actions: actions)
        template.updateSections(sections)
        NSLog("[CarPlay] updateSections favorites count=%d", favorites.count)
    }

    private func updateLibraryTemplate() {
        guard let template = libraryTemplate, let actions = rootActions else {
            NSLog("[CarPlay] updateLibraryTemplate skipped: no template")
            return
        }
        let sections = RootTemplateBuilder.makeLibrarySections(buckets: libraryBuckets, actions: actions)
        template.updateSections(sections)
        NSLog("[CarPlay] updateSections library buckets=%d", libraryBuckets.count)
    }

    private func updatePlaylistsTemplate() {
        guard let template = playlistsTemplate, let actions = rootActions else {
            NSLog("[CarPlay] updatePlaylistsTemplate skipped: no template")
            return
        }
        let sections = RootTemplateBuilder.makePlaylistsSections(playlists: playlists, actions: actions)
        template.updateSections(sections)
        NSLog("[CarPlay] updateSections playlists count=%d", playlists.count)
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
