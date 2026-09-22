# Claude Code Proxy menu-bar app

Native SwiftUI menu-bar client for the Claude Code Proxy dashboard. It targets
macOS 13 or newer and mirrors the web console's overview, account states, and
`All`, `Authenticated`, and `Usable` account filters.

The GitHub `Release Claude Code Proxy macOS app` workflow builds an ad-hoc-signed
ZIP, renders overview/accounts screenshots, and publishes all three files to a
GitHub Release. Ad-hoc signing is suitable for local installation; a Developer
ID certificate and Apple notarization are required for frictionless public
distribution.
