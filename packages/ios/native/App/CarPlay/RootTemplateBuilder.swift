import CarPlay
import UIKit

enum RootTemplateBuilder {
    struct Actions {
        let pushTemplate: (CPTemplate) -> Void
        let showNowPlaying: () -> Void
        let onFavoriteTrackSelected: (CarPlayTrackSnapshot) -> Void
        let onLibraryBucketSelected: (CarPlayLibraryBucketSnapshot) -> Void
        let onLibraryCollectionSelected: (String, CarPlayCollectionSnapshot) -> Void
        let onLibraryTrackSelected: (String, String?, CarPlayTrackSnapshot) -> Void
        let onPlaylistSelected: (CarPlayPlaylistSnapshot) -> Void
        let onPlaylistTrackSelected: (String, CarPlayTrackSnapshot) -> Void
    }

    struct RootTemplates {
        let tabBar: CPTabBarTemplate
        let favorites: CPListTemplate
        let library: CPListTemplate
        let playlists: CPListTemplate
    }

    static func buildRootTemplate(
        state: CarPlayTemplateState,
        actions: Actions
    ) -> RootTemplates {
        let favoritesTemplate = makeFavoritesTemplate(
            favorites: state.favorites,
            actions: actions
        )
        let libraryTemplate = makeLibraryTemplate(
            buckets: state.libraryBuckets,
            actions: actions
        )
        let playlistsTemplate = makePlaylistsTemplate(
            playlists: state.playlists,
            actions: actions
        )
        let tabBar = CPTabBarTemplate(templates: [favoritesTemplate, libraryTemplate, playlistsTemplate])
        return RootTemplates(
            tabBar: tabBar,
            favorites: favoritesTemplate,
            library: libraryTemplate,
            playlists: playlistsTemplate
        )
    }

    // MARK: - Section builders (called per-update for in-place CPListTemplate.updateSections)

    static func makeFavoritesSections(
        favorites: [CarPlayTrackSnapshot],
        actions: Actions
    ) -> [CPListSection] {
        let items: [CPListItem] = favorites.isEmpty
            ? [placeholderItem(text: "Favorite tracks appear here.")]
            : favorites.map { track in
                let item = CPListItem(text: track.title, detailText: track.subtitle)
                item.handler = { _, completion in
                    actions.onFavoriteTrackSelected(track)
                    actions.showNowPlaying()
                    completion()
                }
                return item
            }
        return [CPListSection(items: items)]
    }

    static func makeLibrarySections(
        buckets: [CarPlayLibraryBucketSnapshot],
        actions: Actions
    ) -> [CPListSection] {
        let items: [CPListItem] = buckets.isEmpty
            ? [placeholderItem(text: "Open Familiar on your iPhone to load CarPlay.")]
            : buckets.map { bucket in
                let item = CPListItem(text: bucket.title, detailText: detailText(for: bucket))
                item.handler = { _, completion in
                    actions.onLibraryBucketSelected(bucket)
                    let detailTemplate: CPListTemplate
                    if let tracks = bucket.tracks, !tracks.isEmpty {
                        detailTemplate = makeTrackTemplate(
                            title: bucket.title,
                            bucketId: bucket.id,
                            parentId: nil,
                            tracks: tracks,
                            actions: actions
                        )
                    } else {
                        detailTemplate = makeCollectionTemplate(
                            title: bucket.title,
                            bucketId: bucket.id,
                            collections: bucket.collections ?? [],
                            actions: actions
                        )
                    }
                    actions.pushTemplate(detailTemplate)
                    completion()
                }
                return item
            }
        return [CPListSection(items: items)]
    }

    static func makePlaylistsSections(
        playlists: [CarPlayPlaylistSnapshot],
        actions: Actions
    ) -> [CPListSection] {
        let items: [CPListItem] = playlists.isEmpty
            ? [placeholderItem(text: "No playlists available yet.")]
            : playlists.map { playlist in
                let item = CPListItem(text: playlist.title, detailText: playlist.subtitle)
                item.handler = { _, completion in
                    actions.onPlaylistSelected(playlist)
                    let detailTemplate = makePlaylistTrackTemplate(
                        title: playlist.title,
                        playlist: playlist,
                        actions: actions
                    )
                    actions.pushTemplate(detailTemplate)
                    completion()
                }
                return item
            }
        return [CPListSection(items: items)]
    }

    // MARK: - Initial template builders (called once on attach)

    private static func makeFavoritesTemplate(
        favorites: [CarPlayTrackSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let template = CPListTemplate(
            title: "Favorites",
            sections: makeFavoritesSections(favorites: favorites, actions: actions)
        )
        template.tabTitle = "Favorites"
        template.tabImage = UIImage(systemName: "heart.fill")
        return template
    }

    private static func makeLibraryTemplate(
        buckets: [CarPlayLibraryBucketSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let template = CPListTemplate(
            title: "Library",
            sections: makeLibrarySections(buckets: buckets, actions: actions)
        )
        template.tabTitle = "Library"
        template.tabImage = UIImage(systemName: "music.note.list")
        return template
    }

    private static func makePlaylistsTemplate(
        playlists: [CarPlayPlaylistSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let template = CPListTemplate(
            title: "Playlists",
            sections: makePlaylistsSections(playlists: playlists, actions: actions)
        )
        template.tabTitle = "Playlists"
        template.tabImage = UIImage(systemName: "music.note")
        return template
    }

    private static func makeCollectionTemplate(
        title: String,
        bucketId: String,
        collections: [CarPlayCollectionSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let items: [CPListItem] = collections.isEmpty
            ? [placeholderItem(text: "Nothing to show yet.")]
            : collections.map { collection in
                let item = CPListItem(text: collection.title, detailText: collection.subtitle)
                item.handler = { _, completion in
                    actions.onLibraryCollectionSelected(bucketId, collection)
                    let detailTemplate = makeTrackTemplate(
                        title: collection.title,
                        bucketId: bucketId,
                        parentId: collection.id,
                        tracks: collection.tracks,
                        actions: actions
                    )
                    actions.pushTemplate(detailTemplate)
                    completion()
                }
                return item
            }

        return makeListTemplate(
            title: title,
            tabTitle: nil,
            tabImageName: nil,
            items: items
        )
    }

    private static func makeTrackTemplate(
        title: String,
        bucketId: String,
        parentId: String?,
        tracks: [CarPlayTrackSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let items: [CPListItem] = tracks.isEmpty
            ? [placeholderItem(text: "Nothing to play yet.")]
            : tracks.map { track in
                let item = CPListItem(text: track.title, detailText: track.subtitle)
                item.handler = { _, completion in
                    actions.onLibraryTrackSelected(bucketId, parentId, track)
                    actions.showNowPlaying()
                    completion()
                }
                return item
            }

        return makeListTemplate(
            title: title,
            tabTitle: nil,
            tabImageName: nil,
            items: items
        )
    }

    private static func makePlaylistTrackTemplate(
        title: String,
        playlist: CarPlayPlaylistSnapshot,
        actions: Actions
    ) -> CPListTemplate {
        let items: [CPListItem] = playlist.tracks.isEmpty
            ? [placeholderItem(text: "No tracks in this playlist.")]
            : playlist.tracks.map { track in
                let item = CPListItem(text: track.title, detailText: track.subtitle)
                item.handler = { _, completion in
                    actions.onPlaylistTrackSelected(playlist.id, track)
                    actions.showNowPlaying()
                    completion()
                }
                return item
            }

        return makeListTemplate(
            title: title,
            tabTitle: nil,
            tabImageName: nil,
            items: items
        )
    }

    private static func makeListTemplate(
        title: String,
        tabTitle: String?,
        tabImageName: String?,
        items: [CPListItem]
    ) -> CPListTemplate {
        let section = CPListSection(items: items)
        let template = CPListTemplate(title: title, sections: [section])
        template.tabTitle = tabTitle
        if let tabImageName {
            template.tabImage = UIImage(systemName: tabImageName)
        }
        return template
    }

    private static func placeholderItem(text: String) -> CPListItem {
        CPListItem(text: text, detailText: nil)
    }

    private static func detailText(for bucket: CarPlayLibraryBucketSnapshot) -> String? {
        if let tracks = bucket.tracks {
            return tracks.isEmpty ? nil : "\(tracks.count) tracks"
        }
        if let collections = bucket.collections {
            return collections.isEmpty ? nil : "\(collections.count) collections"
        }
        return nil
    }
}
