import CarPlay
import UIKit

/// Builds the root `CPTabBarTemplate` and handles navigation for CarPlay.
///
/// Phase 3 implementation: Uses tracks provided by `CarPlayDataBridge` to render
/// real list templates instead of placeholders.
enum RootTemplateBuilder {
    static func buildRootTemplate(
        library: [CarPlayTrack] = [],
        collections: [CarPlayCollection] = []
    ) -> CPTabBarTemplate {
        let libraryTab = makeListTemplate(
            title: "Library",
            tabImage: UIImage(systemName: "music.note.list"),
            items: library.map { track in
                CPListItem(text: track.title, detailText: track.subtitle)
            }
        )
        
        let playlistsTab = makeListTemplate(
            title: "Playlists",
            tabImage: UIImage(systemName: "music.note"),
            items: collections.map { collection in
                CPListItem(text: collection.title, detailText: collection.subtitle)
            }
        )
        
        let favoritesTab = makePlaceholderListTemplate(
            title: "Favorites",
            tabImage: UIImage(systemName: "heart.fill"),
            message: "No favorites yet."
        )

        let tabBar = CPTabBarTemplate(templates: [libraryTab, playlistsTab, favoritesTab])
        return tabBar
    }

    static func makeNowPlayingTemplate(for track: CarPlayTrack) -> CPNowPlayingTemplate {
        _ = track
        return CPNowPlayingTemplate.shared
    }

    private static func makeListTemplate(
        title: String,
        tabImage: UIImage?,
        items: [CPListItem]
    ) -> CPListTemplate {
        let section = CPListSection(items: items)
        let listTemplate = CPListTemplate(title: title, sections: [section])
        listTemplate.tabTitle = title
        listTemplate.tabImage = tabImage
        return listTemplate
    }

    private static func makePlaceholderListTemplate(
        title: String,
        tabImage: UIImage?,
        message: String
    ) -> CPListTemplate {
        let item = CPListItem(text: message, detailText: nil)
        let section = CPListSection(items: [item])
        let listTemplate = CPListTemplate(title: title, sections: [section])
        listTemplate.tabTitle = title
        listTemplate.tabImage = tabImage
        return listTemplate
    }
}
