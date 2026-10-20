# Yuketang Helper Windows Desktop

[中文说明](README.md) · [Windows releases](https://github.com/sijiaohanshusin/YuKeTang-Fisher-Helper/releases/latest)

Download the Windows x64 installer and follow the five-step setup wizard: verify your account by scanning the login QR code, configure and test an image-capable AI model, select joined classes, choose the runtime mode, then review and save.

The installer requires neither Python nor Node.js nor administrator access. A portable ZIP and a checksum-verifying deployment script are also provided. New installations start in observation mode with attendance and answer submission disabled. Existing local settings are retained.

Attendance and answer submission have separate switches. AI trial mode displays answers without submitting them. Automatic mode can submit valid AI answers for selected classes. Missing configuration, model errors, invalid output, insufficient time and unsupported question types are reported and skipped. There is no random or blank fallback. Duplicate questions and uncertain POST outcomes are recorded to prevent blind retries.

Single-choice, multiple-choice, voting and short-answer payloads pass local HTTP simulation. Fill-in-the-blank questions remain unsupported. Real login, classroom discovery, attendance, classroom WebSocket connection and a single-choice AI preview have been verified on Windows. Real answer acceptance, grading, other question types and consecutive live classes still need classroom validation. The 16-case diagnostic uses simulated AI and a loopback HTTP server; it produces no real classroom requests.

The console shows discovery health, classroom heartbeats, question details, AI answers and server acceptance separately. Closing the browser keeps the backend running. Computer sleep, shutdown and network loss interrupt monitoring. Use the Start menu stop shortcut or portable `stop.cmd` to stop the backend.

Installer data is stored under `%LOCALAPPDATA%\YuketangHelper`; portable data is stored beside the executable. Distribution packages contain no personal sessions, keys or classroom records. Uninstalling retains personal data. Binaries are not publisher-signed; verify the provided SHA256 checksums.

For source development on Windows, initialize with `init-local.bat`, then use `start-local.bat`, `stop-local.bat` and `logs-local.bat`. Python 3.11 and the locked dependencies have been tested. Only Windows x64 distribution is currently verified.

Community: thanks to [LINUX DO](https://linux.do/) for providing a place to share software and discuss development.

See [distribution instructions](分发使用说明.md), [validation record](验证记录.md), [release notes](RELEASE_NOTES.md), and [third-party notices](THIRD_PARTY_NOTICES.md). This fork is based on [Nijika-jia/YuKeTang-Fisher-Helper](https://github.com/Nijika-jia/YuKeTang-Fisher-Helper) at `cc46b316fe3b37499f463e28e5a8f634df1416e8`; attribution and license statements are retained in the notices.
