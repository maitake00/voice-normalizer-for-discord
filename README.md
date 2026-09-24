# Voice Normalizer for Discord

English | [日本語](README.ja.md)

Automatically evens out the volume of each person in your Discord voice calls, on your side only.

> **This is a test version.** It is still being validated in real calls, so behavior and defaults may change.

## Download

Download the latest `VoiceNormalizerForDiscord-vX.Y.Z.zip` from [Releases](../../releases), extract it, and read `README.txt` inside.

- Requirements: Windows 11 recommended, and the Discord desktop app (the browser version is not supported)
- The exe is built from this repository's source by [GitHub Actions](.github/workflows/release.yml). Each release includes a build attestation and a SHA256 checksum, so you can verify that your download was built here (see the release notes for how).
- The exe is not code-signed, so Windows may show "Windows protected your PC" the first time. Click [More info] → [Run anyway].

## How it works: no audio processing

Discord has no built-in way to even out speakers automatically; you can only drag each person's volume slider (0–200%) by hand. Discord's output is also a single mixed stream, so the operating system can't separate speakers.

So this tool never touches the audio. It **measures loudness and adjusts Discord's own per-user volume setting**, like turning the sliders for you.

- No added latency and no change in sound quality
- The adjusted volumes are saved by Discord itself (they stay when the tool is closed)

```
[capture]   Capture only Discord's audio output (WASAPI process loopback)
[speaking]  Who is speaking (Discord RPC SPEAKING_START / SPEAKING_STOP)
[core]      K-weighted loudness estimate + control loop (pure logic)
[sink]      Write each user's volume % (Discord RPC)
```

Only moments when exactly one person is speaking are measured. A high percentile of each person's loudness is treated as "their voice level", and the volume is moved toward the target slowly, with a dead band and a per-step limit.

## Privacy and disclaimer

- **Audio is analyzed in memory only. It is never saved or sent anywhere.**
  Only [capture/windows_process.py](src/voice_normalizer_for_discord/capture/windows_process.py) (capture) and [core/loudness.py](src/voice_normalizer_for_discord/core/loudness.py) (loudness in dB) touch audio, and samples are discarded after measuring. The only network traffic is the local Discord RPC connection and the OAuth token exchange with Discord.
  (Only if you enable `debug.frame_log`, a numeric log of dB values is saved locally. It contains no audio.)
- This is not an official Discord product. **Use at your own risk.**
- Client plugin backends (such as Vencord) may be added later. They modify the Discord client, which is a gray area under Discord's Terms of Service; the default backend is RPC.

## Usage

1. Run `VoiceNormalizerForDiscord.exe`
2. On first launch, a 3-step setup guide appears. Follow it to create your own Discord application and paste its Client ID and Client Secret.
   (Unapproved apps can't use Discord RPC, so each user needs their own application. Creating one is free, and the owner of an application can use RPC without approval.)
3. On first launch only, Discord shows a confirmation prompt. Click [Authorize].
4. Join a voice call as usual.

The tool starts automatically. If Discord isn't running or the connection drops, it reconnects every 5 seconds. It also follows you when you leave a call or switch channels.

Reading the screen:

- The top card shows the current status and what to do next. While adjusting, "Receiving audio" and "Voices detected" show that everything is working.
- Each member card shows their Discord volume (%) and progress (learning → adjusting → just right). Whoever is speaking gets a green border.
- "Show numbers" displays loudness (dB) and the distance from the target.
- [Settings] changes the target volume, the balancing style (see below), and the language (English / Japanese; defaults to your Windows display language).

Settings are stored in `%APPDATA%\VoiceNormalizerForDiscord\config.toml`.

**Important:** In Discord, set User Settings → Voice & Video → **Attenuation to 0%**. With attenuation on, Discord lowers other sounds when someone speaks, which corrupts the measurements (the tool warns you if it is on).

## Balancing: a trade-off (important)

There is no technically correct answer here; it is **a policy choice**. The "Balancing" setting chooses which part of each person's loudness to match (the `percentile` parameter).

- **Higher (around the 90th percentile)**: loud peaks are matched. Easy on your ears, but people who mumble stay hard to hear.
- **Lower (around the median)**: quiet speakers become easier to hear, but when they shout, it gets loud.

The default (87.5) leans toward protecting your ears. Adjust it for the people you talk with.

## Known limitations

- **Go Live (stream) audio can't be excluded.** Discord itself plays it, so process-level capture can't tell it apart, and it affects measurements while you watch a stream.
- Someone who is still too quiet at 200% can't be helped (Discord's limit). The tool tells you to ask them to turn up their microphone.
- Moments when two or more people speak at once are skipped. The skip rate is shown in the log.
- If the PC can't capture Discord's audio alone (process loopback needs Windows 10 build 20348+ or Windows 11), the tool falls back to capturing all output and shows a warning. Games or music will then affect measurements.

## For developers

### Tests

The core logic (`core/`) is pure and fully separated from OS and I/O. It has convergence tests using synthetic voices, and the engine has integration tests with a fake Discord and a fake audio device.

```powershell
pip install -e .[dev]
pytest
```

### Build the exe / distribution zip

```powershell
pip install -e .[dev]
python packaging\make_release.py
# -> dist\VoiceNormalizerForDiscord.exe and release\VoiceNormalizerForDiscord-v<version>.zip
```

Public builds are not made locally. When a `v*` tag is pushed, [release.yml](.github/workflows/release.yml) runs the tests, builds the exe, attaches the SHA256 and build attestation, and creates the release.

### CLI

With the Discord desktop app running:

```powershell
pip install .
copy config.example.toml config.toml
# fill in client_id / client_secret in config.toml
voice-normalizer-for-discord --config config.toml
```

### Parameters

Only these parameters are configurable ([config.example.toml](config.example.toml)):

| Name | Description | Default |
|---|---|---|
| `target_db` | Target loudness | -24.0 |
| `percentile` | Percentile treated as a person's voice level | 87.5 |
| `window` | Histogram window length (blocks of 100 ms) | 600 |
| `min_samples` | Minimum samples before adjusting a person | 50 |
| `deadband_db` | Differences smaller than this are left alone | 1.5 |
| `max_step_db` | Maximum change per adjustment | 3.0 |

### Audio capture

Like OBS's "Application Audio Capture", the tool uses **WASAPI process loopback** (`ActivateAudioInterfaceAsync` + `AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS`) to capture **only the audio played by Discord's process tree**. Sound from games and other apps is not included.

## License

[MIT](LICENSE)
