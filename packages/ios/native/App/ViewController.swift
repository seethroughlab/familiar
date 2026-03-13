import UIKit
import Capacitor

class ViewController: CAPBridgeViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        // Fix: WKWebView can initialize at wrong zoom scale on cold launch.
        // Lock the scrollView zoom to 1.0 so the viewport meta is always respected.
        webView?.scrollView.minimumZoomScale = 1.0
        webView?.scrollView.maximumZoomScale = 1.0
        webView?.scrollView.zoomScale = 1.0
    }
}
