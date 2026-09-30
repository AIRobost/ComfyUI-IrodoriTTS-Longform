# ComfyUI-IrodoriTTS-Longform

**English** | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [한국어](README.ko.md)

Long-form Japanese text-to-speech for ComfyUI.
Paste a whole script, and this node generates it part by part with
[Irodori-TTS](https://github.com/Aratako/Irodori-TTS) with **one consistent voice from the first line to the last**, then joins everything into one audio file.

Built on top of [comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS).

## Why

Irodori-TTS sounds great on short lines, but a long script has to be split.
Generating each part separately (even with a fixed seed) makes the voice, loudness and acting drift, and every seam is audible.
This node fixes the voice of every part to the same reference and evens out loudness and pauses, so the parts sound like one performance.

## How it works

```
script
  │  split at "---" lines (or by paragraphs), map stage directions / emoji
  ▼
part 1 ──► generate ──► becomes the ANCHOR voice for every later part
part 2 ──► generate (ref: anchor)
part 3 ──► generate (ref: anchor)
  …
  ▼
trim silence ▸ match loudness ▸ insert pauses ▸ join  ──►  one audio
```

- **Anchor**: part 1 (or your reference audio) fixes the voice, so it does not drift from part to part.
- **Even joins**: silence is trimmed, loudness is matched and pauses are inserted, so the seams are not audible.
- References are passed as codec latents, so no extra audio decoding libraries are needed.

> Why not feed the previous part back as a reference? We tried: generated audio used as a reference
> accumulates small artifacts, and phrase endings become hoarse after a few parts. It is still available
> as an experimental option (`context_seconds`), but the anchor-only default is the most stable.

## Requirements

- ComfyUI
- [comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) and its requirements
- An Irodori-TTS v4.1 checkpoint, for example
  [Aratako/Irodori-TTS-v4.1-Small](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small) or
  [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime)

Tested on Windows 11, ComfyUI 0.38, RTX 2060 (6 GB), comfy-IrodoriTTS `60b5724`.
No additional Python packages are required.

## Installation

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/AIRobost/ComfyUI-IrodoriTTS-Longform.git
```

Restart ComfyUI. The node appears as **IrodoriTTS Long-form Sampler** in the `IrodoriTTS Longform` category.

## Usage

Open [`workflows/irodori_longform_example.json`](workflows/irodori_longform_example.json), or connect:

```
IrodoriTTS Model Loader ──► IrodoriTTS Long-form Sampler ──► Save Audio
IrodoriTTS VoiceDesign Config ──┘         └──► (log) Preview as Text
IrodoriTTS Reference Audio (optional) ──┘
```

### Script format

**Just paste your script.** It is split automatically: paragraphs (separated by blank lines) are grouped up to `max_chars` characters per part, and paragraphs that are too long are split at line breaks and sentence ends (。！？). Novels and scripts without blank lines work too.

To decide yourself where scenes break (and how long the pause is), add lines with only `---`:

```
First part of the script.
It can span several lines.
--- 1.2
Second part. The "--- 1.2" line above means a 1.2 s pause before it.
---
Third part (default pause).
```

Blocks between `---` lines are kept as they are (only blocks longer than 2 × `max_chars` are split further).
Parts of 60–120 Japanese characters (about 10–20 s) work best.

### Inputs

| Input | Description |
|---|---|
| `script` | The whole script. Emoji annotations of Irodori-TTS (🤭 😮‍💨 ⏸️ 👂 …) can be used. |
| `seed` | Base seed. Part N uses `seed + N - 1`. |
| `split_mode` | `auto` (use `---` if present, otherwise split automatically), `separator (---)`, `paragraph` (always split automatically) |
| `max_chars` | Target max characters per part for automatic splitting. |
| `pause_seconds` | Default pause between parts. |
| `context_seconds` | Experimental. Seconds of the previous part (phrase endings removed) added as a second reference. **0 (anchor only) is recommended**; higher values can make phrase endings hoarse. |
| `num_steps` | Sampling steps per part. |
| `clean_text` | Maps unsupported emoji and stage directions such as `(sigh)` / `（はぁ…）` to Irodori emoji. |
| `part_seeds` | Re-roll specific parts, e.g. `3:1234, 5:99`. Parts after it also change, because they follow it. |
| `voice_design_config` | (optional) Caption describing the voice, shared by all parts. |
| `ref_config` | (optional) Reference audio for voice cloning. Used as the anchor voice. |
| `lora_stack`, `cfg_config` | (optional) Same as the original sampler. |

Outputs: `audio` (joined audio) and `log` (length / seed of each part and the text changes made by `clean_text`).

### Tips

- On GPUs without bf16 support (e.g. RTX 20 series), set `model_precision` / `codec_precision` to **fp32** in the Model Loader.
- To redo a part you do not like, check its number in the log and set `part_seeds`.
- 🥤 in Irodori-TTS means a *gulp* sound, not a drink.

## Ethical use

Please follow the restrictions of the Irodori-TTS models:

- Do **not** clone or impersonate the voice of any real person (voice actors, celebrities, public figures, …) without their explicit consent.
- Do **not** create deepfakes or speech intended to mislead people or spread misinformation.
- When you publish generated audio, please make clear that it is AI-generated.

## Credits

- [Aratako/Irodori-TTS](https://github.com/Aratako/Irodori-TTS) — the TTS model (MIT)
- [kjranyone/comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) — ComfyUI nodes this project builds on (MIT)
- [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime) — anime-style fine-tune (MIT)
- [facebookresearch/dacvae](https://github.com/facebookresearch/dacvae) — audio codec

## License

[MIT](LICENSE) © 2026 AIRobost
