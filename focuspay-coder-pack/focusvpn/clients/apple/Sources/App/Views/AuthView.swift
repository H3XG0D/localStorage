import SwiftUI

struct AuthView: View {
    @EnvironmentObject private var model: AppModel
    @State private var email = ""
    @State private var password = ""
    @State private var api = ""

    var body: some View {
        VStack(spacing: 16) {
            Text("FocusVPN")
                .font(.system(size: 28, weight: .bold))
                .foregroundStyle(Theme.textPrimary)
            Text("доп. сервис FocusPay")
                .font(.system(size: 13))
                .foregroundStyle(Theme.textMuted)

            VStack(spacing: 12) {
                field("Email", text: $email)
                SecureField("Пароль", text: $password)
                    .textFieldStyle(.plain)
                    .padding(12)
                    .background(Theme.bgInput)
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.border))
                    .foregroundStyle(Theme.textPrimary)
                field("API", text: $api)

                if let err = model.error, !err.isEmpty {
                    Text(err).font(.footnote).foregroundStyle(Theme.danger)
                }

                Button("Регистрация") {
                    Task { await model.register(email: email.trimmingCharacters(in: .whitespaces), password: password, apiBase: api.trimmingCharacters(in: .whitespaces)) }
                }
                .buttonStyle(.bordered)
                .disabled(model.busy)
                .frame(maxWidth: .infinity)

                Button("Войти") {
                    Task { await model.login(email: email.trimmingCharacters(in: .whitespaces), password: password, apiBase: api.trimmingCharacters(in: .whitespaces)) }
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.accent)
                .disabled(model.busy)
                .frame(maxWidth: .infinity)
            }
            .padding(18)
            .background(Theme.bgSurface)
            .clipShape(RoundedRectangle(cornerRadius: 16))

            Text("FocusPay · FocusVPN")
                .font(.system(size: 12))
                .foregroundStyle(Theme.textMuted)
        }
        .padding(22)
        .frame(maxWidth: 420)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.bgBase)
        .onAppear { if api.isEmpty { api = model.apiBase } }
    }

    private func field(_ title: String, text: Binding<String>) -> some View {
        TextField(title, text: text)
            .textFieldStyle(.plain)
            .padding(12)
            .background(Theme.bgInput)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.border))
            .foregroundStyle(Theme.textPrimary)
            #if os(iOS)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            #endif
    }
}
