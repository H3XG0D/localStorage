import SwiftUI

struct LocationsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                ForEach(model.endpoints) { ep in
                    Button {
                        model.selectNode(ep.node)
                        dismiss()
                    } label: {
                        HStack {
                            VStack(alignment: .leading) {
                                Text(ep.node).foregroundStyle(Theme.textPrimary)
                                Text("\(ep.country ?? "") \(ep.region ?? "")")
                                    .font(.caption)
                                    .foregroundStyle(Theme.textMuted)
                            }
                            Spacer()
                            if model.selectedNode == ep.node {
                                Text("✓").foregroundStyle(Theme.ok)
                            }
                        }
                    }
                    .listRowBackground(Theme.bgSurface)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.bgBase)
            .navigationTitle("Локации")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Закрыть") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button("Обновить") { Task { await model.refreshServers() } }
                        .disabled(model.busy)
                }
            }
        }
        .preferredColorScheme(.dark)
        .onAppear { Task { await model.refreshServers() } }
    }
}
