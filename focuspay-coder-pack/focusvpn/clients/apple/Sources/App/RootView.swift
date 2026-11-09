import SwiftUI

struct RootView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Group {
            if model.loggedIn {
                HomeView()
            } else {
                AuthView()
            }
        }
        .background(Theme.bgBase.ignoresSafeArea())
    }
}
