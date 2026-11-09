// Package frontend embeds the desktop UI (same screens as Android) for Wails.
package frontend

import "embed"

// FS holds index.html, theme.css, app.js, and Onest.
//
//go:embed index.html theme.css app.js fonts/*.ttf
var FS embed.FS
