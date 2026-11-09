// Theme.swift — светлая тема «обменник» (зеркало clients/desktop/frontend/theme.css)
import SwiftUI

enum Theme {
    static let bgBase = Color(red: 0xF4 / 255, green: 0xF6 / 255, blue: 0xFA / 255)
    static let bgSurface = Color.white
    static let bgInput = Color(red: 0xF1 / 255, green: 0xF4 / 255, blue: 0xF9 / 255)
    static let bgTicker = Color(red: 0x0E / 255, green: 0x1B / 255, blue: 0x33 / 255)
    static let border = Color(red: 0xE2 / 255, green: 0xE8 / 255, blue: 0xF2 / 255)
    static let textPrimary = Color(red: 0x0F / 255, green: 0x1E / 255, blue: 0x33 / 255)
    static let textMuted = Color(red: 0x64 / 255, green: 0x74 / 255, blue: 0x8B / 255)
    static let textLabel = Color(red: 0x8A / 255, green: 0x97 / 255, blue: 0xAD / 255)
    static let accent = Color(red: 0x1A / 255, green: 0x6C / 255, blue: 0xFF / 255)
    static let accentSoft = Color(red: 0xE8 / 255, green: 0xF0 / 255, blue: 0xFF / 255)
    static let danger = Color(red: 0xDC / 255, green: 0x26 / 255, blue: 0x26 / 255)
    static let ok = Color(red: 0x16 / 255, green: 0xA3 / 255, blue: 0x4A / 255)
    static let okSoft = Color(red: 0xE5 / 255, green: 0xF7 / 255, blue: 0xEC / 255)
    static let amber = Color(red: 0xD9 / 255, green: 0x77 / 255, blue: 0x06 / 255)
}
