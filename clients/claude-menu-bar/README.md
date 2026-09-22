# Claude Code Proxy menu-bar app

Native SwiftUI menu-bar client for the Claude Code Proxy dashboard. It targets
macOS 13 or newer and mirrors the web console's overview, account states, and
`All`, `Authenticated`, and `Usable` account filters.

Open the gear button to enter the proxy base URL and the same username and
password used by the dashboard. The app validates them through the dashboard
login endpoint and stores the password and returned session token in the macOS
Keychain. No server URL or organization identity is compiled into the app.

The GitHub `Release Claude Code Proxy macOS app` workflow builds an ad-hoc-signed
DMG installer and publishes it to a GitHub Release. Open the disk image and drag
**Claude Code Proxy.app** to Applications. Ad-hoc signing is suitable for local installation; a Developer
ID certificate and Apple notarization are required for frictionless public
distribution.
