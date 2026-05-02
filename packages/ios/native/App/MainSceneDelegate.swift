import UIKit
import Capacitor

class MainSceneDelegate: UIResponder, UIWindowSceneDelegate {

    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = (scene as? UIWindowScene) else { return }
        let window = UIWindow(windowScene: windowScene)
        let storyboard = UIStoryboard(name: "Main", bundle: nil)
        window.rootViewController = storyboard.instantiateInitialViewController()
        self.window = window
        window.makeKeyAndVisible()
    }

    func sceneDidDisconnect(_ scene: UIScene) {
        // Called when the scene is being disconnected from the application.
    }

    func sceneDidBecomeActive(_ scene: UIScene) {
        // Called when the scene becomes the appropriate foreground interface for the application.
    }

    func sceneWillResignActive(_ scene: UIScene) {
        // Called when the scene is about to move from an active to an inactive state.
    }

    func sceneWillEnterForeground(_ scene: UIScene) {
        // Called when the scene is transitioning from a background state to an active state.
    }

    func sceneDidEnterBackground(_ scene: UIScene) {
        // Called when the scene is in a background state.
    }
    
    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        // Handle user activity (e.g., Universal Links).
    }
}
