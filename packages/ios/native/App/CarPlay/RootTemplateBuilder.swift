import CarPlay
import UIKit

/// Builds the root `CPTabBarTemplate` shown when the user connects CarPlay.
///
/// Pass 1 scaffolding: each tab renders a placeholder `CPListTemplate` with a
/// single "Loading…" item. Pass 2 will wire these tabs to a JS data bridge
/// (see `CarPlayDataBridge.swift`) that fetches library / playlists / favorites
/// from the existing frontend APIs.
enum RootTemplateBuilder {
    static func buildRootTemplate() -> CPTabBarTemplate {
        let libraryTab = makePlaceholderListTemplate(
            title: "Library",
            tabImage: UIImage(systemName: "music.note.list"),
            message: "Browsing your library here — data bridge pending."
        )
        let playlistsTab = makePlaceholderListTemplate(
            title: "Playlists",
            tabImage: UIImage(systemName: "music.note"),
            message: "Your playlists — data bridge pending."
        )
        let favoritesTab = makePlaceholderListTemplate(
            title: "Favorites",
            tabImage: UIImage(systemName: "heart.fill"),
            message: "Your favorites — data bridge pending."
        )
        let claudeTab = makePlaceholderListTemplate(
            title: "Claude",
            tabImage: UIImage(systemName: "sparkles"),
            message: "Ask Claude for music — data bridge pending."
        )

        let tabBar = CPTabBarTemplate(templates: [libraryTab, playlistsTab, favoritesTab, claudeTab])
        return tabBar
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
