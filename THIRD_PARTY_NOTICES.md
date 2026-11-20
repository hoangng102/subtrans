# Third-party notices

SubTrans is MIT-licensed (see `LICENSE`). It uses the following components, each under its own license.
Check the upstream projects for the full texts.

## Bundled in this repository
| Component | Use | License |
|---|---|---|
| Inter (fonts in `assets/fonts`) | UI font | SIL Open Font License 1.1 (`assets/fonts/Inter-LICENSE.txt`) |
| JetBrains Mono (fonts in `assets/fonts`) | UI monospace font | SIL Open Font License 1.1 (`assets/fonts/JetBrainsMono-OFL.txt`) |

## Python dependencies (installed with pip, not bundled in source)
| Package | License (upstream) |
|---|---|
| faster-whisper, CTranslate2 | MIT |
| rapidocr-onnxruntime, onnxruntime | Apache-2.0, MIT |
| Pillow | HPND (MIT-style) |
| NumPy | BSD-3-Clause |
| tkinterdnd2 | MIT |
| anthropic (optional SDK) | MIT |
| huggingface_hub | Apache-2.0 |

## Models downloaded at run time
- Whisper models (`small`, `medium`, `large-v3-turbo`, ...) are downloaded from Hugging Face on first use. Whisper is released by OpenAI under the MIT license.

## External programs (not included)
- **FFmpeg / ffprobe**: must be installed separately (or shipped by a packager). FFmpeg is LGPL/GPL depending on the build; if you redistribute a build, follow its license terms.
- **VLC**: optional, used to play videos and for the live subtitle panel. Not included.

## AI services (optional, bring your own key)
Claude (Anthropic), OpenAI, Gemini, Groq and other providers are used only if you enter your own API key. Their terms of service and usage policies apply to your use.
