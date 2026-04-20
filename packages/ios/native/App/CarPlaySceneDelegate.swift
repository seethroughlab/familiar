import CarPlay
import UIKit

/// Scene delegate for CarPlay. iOS calls this when the user connects a CarPlay
/// head unit (or when the Xcode CarPlay simulator attaches). The delegate's
/// sole responsibility in Pass 1 is to set a root `CPTabBarTemplate` on the
/// provided interface controller.
///
/// Pass 2 will add a `CarPlayDataBridge` member that talks to the existing
/// `FamiliarAudioPlugin` to populate the tabs and handle track selection.
@available(iOS 14.0, *)
final class CarPlaySceneDelegate: UIResponder, CPTemplateApplicationSceneDelegate {
    private var interfaceController: CPInterfaceController?

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didConnect interfaceController: CPInterfaceController
    ) {
        self.interfaceController = interfaceController
        let root = RootTemplateBuilder.buildRootTemplate()
        interfaceController.setRootTemplate(root, animated: false, completion: nil)
    }

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didDisconnectInterfaceController interfaceController: CPInterfaceController
    ) {
        self.interfaceController = nil
    }
}
