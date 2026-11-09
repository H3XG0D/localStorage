import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showLocations = false
    @State private var showAccount = false

    var body: some View {
        VStack(spacing: 20) {
            HStack {
                Text("FocusVPN")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Theme.textPrimary)
                Spacer()
                Button("Аккаунт") { showAccount = true }
                    .foregroundStyle(Theme.accent)
            }

            VStack(spacing: 14) {
                Text(model.connected ? "Подключено" : "Отключено")
                    .font(.title2.bold())
                    .foregroundStyle(model.connected ? Theme.ok : Theme.textMuted)

                Text(model.selectedNode ?? "локация не выбрана")
                    .foregroundStyle(Theme.textMuted)

                if let ep = model.endpointHint {
                    Text(ep)
                        .font(.caption)
                        .foregroundStyle(Theme.textMuted)
                }
                if let jc = model.lastJc {
                    Text("Jc=\(jc)")
                        .font(.caption)
                        .foregroundStyle(Theme.textMuted)
                }

                if let err = model.error, !err.isEmpty {
                    Text(err).font(.footnote).foregroundStyle(Theme.danger)
                }

                Button(model.connected ? "Отключить" : "Подключить") {
                    Task {
                        if model.connected { await model.disconnect() }
                        else { await model.connect() }
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(model.connected ? Theme.danger : Theme.accent)
                .disabled(model.busy)
                .frame(maxWidth: .infinity)

                Button("Локации") { showLocations = true }
                    .foregroundStyle(Theme.accent)
            }
            .padding(22)
            .frame(maxWidth: .infinity)
            .background(Theme.bgSurface)
            .clipShape(RoundedRectangle(cornerRadius: 16))

            Spacer()
        }
        .padding(22)
        .background(Theme.bgBase)
        .sheet(isPresented: $showLocations) { LocationsView() }
        .sheet(isPresented: $showAccount) { AccountView() }
    }
}
