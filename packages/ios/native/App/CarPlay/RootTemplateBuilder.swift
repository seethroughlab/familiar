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

    static func buildRootTemplate(
        state: CarPlayTemplateState,
        actions: Actions
    ) -> CPTabBarTemplate {
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

        return CPTabBarTemplate(templates: [favoritesTemplate, libraryTemplate, playlistsTemplate])
    }

    private static func makeFavoritesTemplate(
        favorites: [CarPlayTrackSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let items = favorites.isEmpty
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

        return makeListTemplate(
            title: "Favorites",
            tabTitle: "Favorites",
            tabImageName: "heart.fill",
            items: items
        )
    }

    private static func makeLibraryTemplate(
        buckets: [CarPlayLibraryBucketSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let items = buckets.isEmpty
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

        return makeListTemplate(
            title: "Library",
            tabTitle: "Library",
            tabImageName: "music.note.list",
            items: items
        )
    }

    private static func makeCollectionTemplate(
        title: String,
        bucketId: String,
        collections: [CarPlayCollectionSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let items = collections.isEmpty
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
        let items = tracks.isEmpty
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

    private static func makePlaylistsTemplate(
        playlists: [CarPlayPlaylistSnapshot],
        actions: Actions
    ) -> CPListTemplate {
        let items = playlists.isEmpty
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

        return makeListTemplate(
            title: "Playlists",
            tabTitle: "Playlists",
            tabImageName: "music.note",
            items: items
        )
    }

    private static func makePlaylistTrackTemplate(
        title: String,
        playlist: CarPlayPlaylistSnapshot,
        actions: Actions
    ) -> CPListTemplate {
        let items = playlist.tracks.isEmpty
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
