# Security policy

## Supported versions

Only the [latest release](https://github.com/Aditya-Prakash-047/ShiftWheel-releases/releases/latest) receives fixes.

## Reporting a problem

Please don't describe a vulnerability in a public issue. Use GitHub's **private vulnerability reporting** on the [ShiftWheel-releases](https://github.com/Aditya-Prakash-047/ShiftWheel-releases/security) page: Security → Report a vulnerability. Include the version (About → Copy details) and steps to reproduce.

## How ShiftWheel handles your files and network

- Files are processed on your computer; nothing is uploaded, and there is no telemetry.
- The only network use is the update check and download from GitHub over HTTPS. It can be turned off in Settings → Behaviour.
- A downloaded update must match the size and SHA-256 published on the release page, or it is deleted and never run.
- Originals are never changed, and archives can't extract outside their destination folder.
- Builds aren't code-signed yet, so Windows and macOS warn on first launch.
