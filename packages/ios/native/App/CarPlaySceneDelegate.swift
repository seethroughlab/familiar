import CarPlay
import UIKit

@available(iOS 14.0, *)
final class CarPlaySceneDelegate: UIResponder, CPTemplateApplicationSceneDelegate {
    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didConnect interfaceController: CPInterfaceController
    ) {
        NSLog("[CarPlay] scene didConnect")
        CarPlayDataBridge.shared.attachInterfaceController(interfaceController)
    }

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didDisconnectInterfaceController interfaceController: CPInterfaceController
    ) {
        NSLog("[CarPlay] scene didDisconnect")
        CarPlayDataBridge.shared.detachInterfaceController(interfaceController)
    }
}
