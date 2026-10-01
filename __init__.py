"""ComfyUI-IrodoriTTS-Longform

Long-form sampler for comfy-IrodoriTTS (https://github.com/kjranyone/comfy-IrodoriTTS).

Splits a script into parts and generates them one by one with the Irodori-TTS
runtime, using part 1 (or the user's reference audio) as the anchor voice for
every part, so the voice stays the same from start to end. The parts are then
trimmed, loudness-matched and joined with pauses.

Optionally (context_seconds > 0, experimental) phrase bodies of the previous
part are added as a second reference. Generated audio fed back as a reference
tends to accumulate artifacts (hoarse phrase endings), so this is off by default.

The Irodori runtime is looked up through NODE_CLASS_MAPPINGS at run time, so
comfy-IrodoriTTS must be installed alongside this node.

Copyright (c) 2026 AIRobost. MIT License.
"""

import re
import sys
import uuid
from pathlib import Path

import comfy.utils
import folder_paths
import torch

SAMPLER_ID = "kjranyone.IrodoriTTS.Sampler"
CATEGORY = "IrodoriTTS Longform"

# Emoji annotations understood by Irodori-TTS v4.1 (EMOJI_ANNOTATIONS.md of the model).
SUPPORTED_EMOJI = {
    "😮‍💨", "🌬️", "⏸️", "👂", "🤭", "🥵", "📢", "😏", "🥺", "😮", "👅", "💋", "🫶", "😭", "😱", "😪",
    "😴", "⏩", "📞", "🐢", "🥤", "🤧", "😒", "😰", "😆", "💥", "😠", "😲", "🥱", "😖", "😟", "🫣",
    "🙄", "😊", "😎", "👌", "🙏", "🥴", "🎵", "🤐", "😌", "🤔", "💪", "👃", "📖",
}
_SUPPORTED_BARE = {e.replace("️", "") for e in SUPPORTED_EMOJI}

# Common emoji the model does not know -> closest supported one ("" = drop).
EMOJI_FALLBACK = {
    "😳": "🫣", "😣": "😖", "😶": "⏸️", "😢": "😭", "😥": "😟", "😅": "😰", "😂": "🤭", "🤣": "🤭",
    "😄": "😆", "😁": "😆", "😃": "😆", "🥰": "🫶", "😍": "🫶", "😘": "💋", "😤": "😠", "😡": "😠",
    "😩": "😖", "😫": "😖", "😓": "😰", "😨": "😰", "😧": "😲", "😯": "😮", "😬": "😰", "🤫": "👂",
    "😑": "🙄", "😐": "⏸️", "🥹": "🥺", "😞": "😟", "😔": "😟", "🎶": "🎵", "💤": "😴",
}

# Stage directions in parentheses -> emoji. Unknown directions are dropped so they are not read aloud.
STAGE_DIRECTIONS = [
    (r"はぁ|ため息|溜息|吐息|sigh", "😮‍💨"),
    (r"すぅ|すー|深呼吸|息を吸|呼吸|breath", "🌬️"),
    (r"息をのむ|息を呑む|gasp", "😮"),
    (r"笑|ふふ|くすくす|laugh|giggle", "🤭"),
    (r"囁|ささや|小声|耳元|whisper", "👂"),
    (r"泣|涙|嗚咽|cry|sob", "😭"),
    (r"間|沈黙|黙|pause|silence", "⏸️"),
    (r"咳|くしゃみ|鼻をすす|cough|sneeze", "🤧"),
    (r"あくび|yawn", "🥱"),
    (r"ごくり|唾を飲|gulp", "🥤"),
    (r"照れ|恥ずかし|shy", "🫣"),
]

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⌀-⏿⬀-⯿]"
    "(?:️|‍[\U0001F000-\U0001FAFF☀-➿]️?)*"
)
_PAREN_RE = re.compile(r"[（(]([^（）()]{1,30})[）)]")
_SEPARATOR_RE = re.compile(r"^\s*(?:-{3,}|={3,}|＝{3,}|ー{3,})\s*([0-9.]+)?\s*$")


def normalize_annotations(text, log):
    """Map stage directions and unsupported emoji to Irodori emoji annotations."""

    def paren(m):
        inner = m.group(1)
        for pattern, emoji in STAGE_DIRECTIONS:
            if re.search(pattern, inner, re.IGNORECASE):
                log.append(f"  ({inner}) -> {emoji}")
                return emoji
        log.append(f"  ({inner}) -> removed")
        return ""

    def emoji(m):
        e = m.group(0)
        if e in SUPPORTED_EMOJI or e.replace("️", "") in _SUPPORTED_BARE:
            return e
        rep = EMOJI_FALLBACK.get(e, EMOJI_FALLBACK.get(e.replace("️", ""), ""))
        log.append(f"  {e} -> {rep or 'removed'}")
        return rep

    text = _PAREN_RE.sub(paren, text)
    text = _EMOJI_RE.sub(emoji, text)
    return re.sub(r"[ \t　]{2,}", " ", text).strip()


_TERMINATORS = "。！？!?♪"
# A sentence ends at 。！？ etc., keeping closing brackets, emoji and spaces that follow it.
_SENTENCE_RE = re.compile(
    rf"[^{_TERMINATORS}]*[{_TERMINATORS}]+(?:[」』）)\]]|{_EMOJI_RE.pattern}|\s)*|[^{_TERMINATORS}]+$"
)


def _split_long(text, max_chars):
    """Split text longer than max_chars at sentence ends, then at commas, then hard."""
    if len(text) <= max_chars:
        return [text]
    pieces = [s for s in _SENTENCE_RE.findall(text) if s.strip()]
    if len(pieces) <= 1:
        pieces = [s for s in re.split(r"(?<=[、，,])", text) if s.strip()]
    if len(pieces) <= 1:
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    out = []
    for p in pieces:
        out += _split_long(p, max_chars) if len(p) > max_chars else [p]
    return out


def _units(text, max_chars):
    """Break text into (unit, joiner) pairs: paragraphs, then lines, then sentences if needed."""
    units = []
    for pi, para in enumerate(p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        lines = [para] if len(para) <= max_chars else [l.strip() for l in para.split("\n") if l.strip()]
        for li, line in enumerate(lines):
            for si, sentence in enumerate(_split_long(line, max_chars)):
                joiner = "\n\n" if li == 0 and si == 0 else ("\n" if si == 0 else "")
                units.append((sentence.strip(), joiner if units else ""))
    return units


def _pack(text, max_chars):
    """Pack units into parts of at most ~max_chars, preferring paragraph and line boundaries."""
    parts, buf = [], ""
    for unit, joiner in _units(text, max_chars):
        if buf and len(buf) + len(unit) > max_chars:
            parts.append(buf)
            buf = unit
        else:
            buf = f"{buf}{joiner}{unit}" if buf else unit
    if buf:
        parts.append(buf)
    return parts


_LINE_END_OK = "。！？!?…‥、，,」』）)]】♪～〜ー―—.:;：；"
_TRAILING_RE = re.compile(rf"((?:{_EMOJI_RE.pattern}|\s)*)$")
_JAPANESE_RE = re.compile(r"[぀-ヿ㐀-鿿]")


def add_missing_periods(text, log):
    """Add '。' to Japanese lines that end without punctuation (before any trailing emoji).

    Irodori-TTS tends to trail off or stretch the ending when a sentence has no final punctuation.
    """
    out, added = [], []
    for line in text.split("\n"):
        tail = _TRAILING_RE.search(line).group(1)
        body = line[: len(line) - len(tail)]
        if body.strip() and _JAPANESE_RE.search(body) and body.rstrip()[-1] not in _LINE_END_OK:
            added.append(body.rstrip()[-8:])
            line = body.rstrip() + "。" + tail
        out.append(line)
    if added:
        shown = ", ".join(f"…{a}" for a in added[:4]) + (f" (+{len(added) - 4})" if len(added) > 4 else "")
        log.append(f"  added 。 to {len(added)} line(s): {shown}")
    return "\n".join(out)


def split_script(script, mode, max_chars, default_pause):
    """Split a script into [(text, pause_after_seconds)].

    Without '---' lines, the script is split automatically: paragraphs are grouped up to
    max_chars, and paragraphs that are too long are split at line breaks and sentence ends.
    Blocks between '---' lines are kept as they are unless they exceed 2 x max_chars.
    """
    script = script.replace("\r\n", "\n")
    lines = script.split("\n")
    parts = []
    use_separator = mode == "separator (---)" or (mode == "auto" and any(_SEPARATOR_RE.match(l) for l in lines))
    if use_separator:
        blocks, buf = [], []
        for line in lines:
            m = _SEPARATOR_RE.match(line)
            if not m:
                buf.append(line)
                continue
            if "\n".join(buf).strip():
                blocks.append(("\n".join(buf).strip(), float(m.group(1)) if m.group(1) else default_pause))
            buf = []
        if "\n".join(buf).strip():
            blocks.append(("\n".join(buf).strip(), default_pause))
        for block, pause in blocks:
            sub = [block] if len(block) <= 2 * max_chars else _pack(block, max_chars)
            parts += [[s, default_pause] for s in sub[:-1]] + [[sub[-1], pause]]
    else:
        parts = [[p, default_pause] for p in _pack(script, max_chars)]
    if parts:
        parts[-1][1] = 0.0
    return [tuple(p) for p in parts]


def parse_part_seeds(spec):
    out = {}
    for tok in re.split(r"[,\s、]+", spec.strip()):
        k, _, v = tok.partition(":")
        if k.strip().isdigit() and v.strip().isdigit():
            out[int(k)] = int(v)
    return out


def load_audio(path):
    """Load audio as ([channels, samples] float32 tensor, sample_rate) without torchcodec."""
    try:
        import soundfile as sf

        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), int(sr)
    except Exception:
        import torchaudio

        wav, sr = torchaudio.load(str(path))
        return wav.float(), int(sr)


def trim_silence(wav, sr, thr_db=-45.0, pad=0.08):
    mono = wav.mean(0)
    frame = max(1, int(sr * 0.02))
    n = mono.shape[0] // frame
    if n == 0:
        return wav
    env = mono[: n * frame].reshape(n, frame).pow(2).mean(1).add(1e-12).sqrt()
    voiced = torch.nonzero(20 * torch.log10(env) > thr_db).flatten()
    if voiced.numel() == 0:
        return wav
    start = max(0, int(voiced[0]) * frame - int(pad * sr))
    end = min(wav.shape[1], (int(voiced[-1]) + 1) * frame + int(pad * sr))
    return wav[:, start:end]


def _phrases(mono, sr, thr_db=-38.0, bridge=0.2, min_len=0.3):
    """Voiced phrases as (start, end) sample ranges; short dips up to `bridge` seconds are bridged."""
    frame = max(1, int(sr * 0.02))
    n = mono.shape[0] // frame
    if n == 0:
        return []
    env = 20 * torch.log10(mono[: n * frame].reshape(n, frame).pow(2).mean(1).add(1e-12).sqrt())
    voiced = (env > thr_db).tolist()
    gap = int(bridge / 0.02)
    out, i = [], 0
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        j = i
        while j < n and (voiced[j] or any(voiced[j:j + gap])):
            j += 1
        if (j - i) * 0.02 >= min_len:
            out.append((i * frame, j * frame))
        i = j
    return out


def clean_context(wav, sr, seconds, drop_tail=0.5):
    """Build a context reference from the previous part without its breathy phrase endings.

    Phrase endings of TTS output tend to be breathy; feeding them back as a reference makes
    the next part breathier, and the effect snowballs. Only phrase bodies are kept, taken from
    the end of the part backwards until `seconds` is reached.
    """
    mono = wav.mean(0)
    pieces, total = [], 0
    for a, b in reversed(_phrases(mono, sr)):
        b = b - int(drop_tail * sr)
        if b - a < int(0.4 * sr):
            continue
        pieces.insert(0, wav[:, a:b])
        total += b - a
        if total >= seconds * sr:
            break
    if not pieces:
        return None
    gap = torch.zeros(wav.shape[0], int(0.15 * sr))
    joined = [pieces[0]]
    for p in pieces[1:]:
        joined += [gap, p]
    return torch.cat(joined, dim=1)[:, -int(seconds * sr):]



class IrodoriTTSLongformSampler:
    DESCRIPTION = (
        "Generate a long script part by part with one consistent voice and join it into one audio. / "
        "長い台本をパートごとに同じ声で生成し、1本の音声につなげます。"
    )
    CATEGORY = CATEGORY
    RETURN_TYPES = ("AUDIO", "STRING", "IRODORI_REF_CONFIG")
    RETURN_NAMES = ("audio", "log", "voice")
    OUTPUT_TOOLTIPS = (
        "Joined audio. / 連結した音声。",
        "Length, seed and text changes of each part. / 各パートの秒数・seed・テキストの変更点。",
        "The voice used for all parts. Connect to Save Voice to reuse it later. / "
        "全パートで使った声。Save Voice につなぐと保存して次回も使えます。",
    )
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_config": ("IRODORI_MODEL_CONFIG", {
                    "tooltip": "Output of IrodoriTTS Model Loader. / IrodoriTTS Model Loader の出力。"}),
                "script": ("STRING", {"multiline": True, "default": "", "tooltip":
                    "Paste the whole script; it is split into parts automatically. Optionally, a line with only '---' "
                    "marks a scene break ('--- 1.5' = 1.5 s pause after it). / 台本を貼るだけで自動でパートに分けます。"
                    "「---」だけの行で場面の区切りを指定することもできます（「--- 1.5」で直後の間を1.5秒に）。"}),
                "seed": ("INT", {"default": 777, "min": 0, "max": sys.maxsize, "tooltip":
                    "Base seed. Part N uses seed + N - 1. / 基準seed。パートNは seed + N - 1 を使います。"}),
                "split_mode": (["auto", "separator (---)", "paragraph"], {"default": "auto", "tooltip":
                    "auto: use '---' if present, otherwise split automatically (paragraphs, lines, sentence ends). / "
                    "auto: 「---」があればそれで区切り、無ければ段落・改行・文末で自動分割します。"}),
                "max_chars": ("INT", {"default": 100, "min": 20, "max": 600, "tooltip":
                    "Target max characters per part for automatic splitting. / 自動分割での1パートの最大文字数の目安。"}),
                "pause_seconds": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 5.0, "step": 0.1, "tooltip":
                    "Default pause between parts. / パート間の間（秒）。"}),
                "context_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 30.0, "step": 1.0, "tooltip":
                    "Experimental. Seconds of the previous part (phrase endings removed) added as a second reference. "
                    "0 = anchor voice only (recommended; feeding generated audio back can make endings hoarse). / "
                    "実験的機能。直前パート（語尾を除く）を参照に足す秒数。0＝パート1の声だけ（推奨。"
                    "生成音声を参照に戻すと語尾がかすれることがあります）。"}),
                "num_steps": ("INT", {"default": 40, "min": 1, "max": 120}),
                "clean_text": ("BOOLEAN", {"default": True, "tooltip":
                    "Map unsupported emoji and stage directions like (sigh) to Irodori emoji, and add a missing '。' "
                    "at the end of Japanese lines. / 未対応の絵文字や（はぁ…）などのト書きを対応する絵文字に変換し、"
                    "句点のない行末に「。」を補います。"}),
                "part_seeds": ("STRING", {"default": "", "tooltip":
                    "Override seeds per part, e.g. '3:1234, 5:99'. Later parts change too (they follow the "
                    "previous part). / パートごとのseed指定。例: 3:1234, 5:99（以降のパートも引き継ぎで変わります）"}),
            },
            "optional": {
                "voice_design_config": ("IRODORI_VOICE_DESIGN_CONFIG", {"tooltip":
                    "Caption (voice description), shared by all parts. / 声の指定（全パート共通）。"}),
                "ref_config": ("IRODORI_REF_CONFIG", {"tooltip":
                    "Reference audio for voice cloning; used as the anchor voice. / 声クローン用の参照音声。"}),
                "lora_stack": ("IRODORI_LORA_STACK",),
                "cfg_config": ("IRODORI_CFG_CONFIG",),
            },
        }

    def run(self, model_config, script, seed, split_mode, max_chars, pause_seconds, context_seconds,
            num_steps, clean_text, part_seeds, voice_design_config=None, ref_config=None,
            lora_stack=None, cfg_config=None):
        import nodes

        sampler_cls = nodes.NODE_CLASS_MAPPINGS.get(SAMPLER_ID)
        if sampler_cls is None:
            raise RuntimeError("comfy-IrodoriTTS is not installed or failed to load.")
        smod = sys.modules[sampler_cls.__module__]
        rmod = sys.modules[smod.SamplingRequest.__module__]

        log = []
        parts = split_script(script, split_mode, max_chars, pause_seconds)
        if clean_text:
            cleaned = []
            for i, (text, pause) in enumerate(parts, 1):
                changes = []
                text = add_missing_periods(normalize_annotations(text, changes), changes)
                if changes:
                    log += [f"[part{i:02d} text]"] + changes
                if text:
                    cleaned.append((text, pause))
            parts = cleaned
        if not parts:
            raise ValueError("The script is empty.")
        seed_overrides = parse_part_seeds(part_seeds)

        caption_cfg = dict(voice_design_config or {})
        cfg = dict(cfg_config or {})
        ref = dict(ref_config or {})
        adapters = tuple((str(e["path"]), float(e.get("strength", 1.0))) for e in (lora_stack or []) if e.get("path"))
        guidance_mode = str(cfg.get("cfg_guidance_mode", "independent"))
        scale_text = float(cfg.get("cfg_scale_text", 3.0))

        runtime, _ = rmod.get_cached_runtime(smod._build_runtime_key(model_config))
        work = Path(folder_paths.get_temp_directory()) / "irodori_longform" / uuid.uuid4().hex
        work.mkdir(parents=True, exist_ok=True)

        def encode(wav, sr, name):
            """Encode a waveform to a codec latent file usable as a reference."""
            with torch.inference_mode():
                z = runtime.codec.encode_waveform(
                    wav.unsqueeze(0).float(), sample_rate=int(sr), normalize_db=-16.0, ensure_max=True
                ).cpu()
            path = work / f"{name}.pt"
            torch.save(z[0].contiguous(), path)
            return str(path)

        # Encode the user's reference audio so it can be combined with the chained context latents.
        user_refs = [str(p) for p in ref.get("ref_latents") or []]
        for i, path in enumerate(ref.get("ref_wavs") or []):
            wav, sr = load_audio(path)
            user_refs.append(encode(wav, sr, f"user_ref_{i}"))

        total = len(parts) * int(num_steps)
        pbar = comfy.utils.ProgressBar(total)
        anchor = context = None
        preview = next(iter(ref.get("ref_wavs") or []), None) or ref.get("voice_preview")
        pieces, out_sr = [], None
        policy = str(model_config.get("runtime_cache_policy", "offload_after_use"))
        try:
            for i, (text, pause) in enumerate(parts, 1):
                refs = user_refs + [r for r in (anchor, context) if r]
                part_seed = seed_overrides.get(i, int(seed) + i - 1)
                done = (i - 1) * int(num_steps)
                request = smod.SamplingRequest(
                    text=text, caption=caption_cfg.get("caption", None), ref_wavs=[], ref_latents=refs,
                    ref_embed=None, no_ref=not refs, ref_normalize_db=None, ref_ensure_max=True,
                    num_candidates=1, decode_mode="sequential", seconds=None, duration_scale=1.0,
                    min_seconds=0.5, max_seconds=60.0, max_ref_seconds=None, max_text_len=None,
                    max_caption_len=caption_cfg.get("max_caption_len", None), num_steps=int(num_steps),
                    cfg_scale_text=scale_text,
                    cfg_scale_caption=float(cfg.get("cfg_scale_caption", caption_cfg.get("cfg_scale_caption", 3.0))),
                    cfg_scale_speaker=float(cfg.get("cfg_scale_speaker", 5.0)), cfg_guidance_mode=guidance_mode,
                    cfg_scale=smod._resolve_cfg_override(cfg, guidance_mode, scale_text),
                    cfg_min_t=float(cfg.get("cfg_min_t", 0.5)), cfg_max_t=float(cfg.get("cfg_max_t", 1.0)),
                    truncation_factor=None, rescale_k=None, rescale_sigma=None, context_kv_cache=True,
                    speaker_kv_scale=None, speaker_kv_min_t=0.9, speaker_kv_max_layers=None,
                    speaker_uncond_mode=str(ref.get("speaker_uncond_mode", "mask")), seed=part_seed,
                    t_schedule_mode="linear", sway_coeff=-1.0, trim_tail=True, tail_window_size=20,
                    tail_std_threshold=0.05, tail_mean_threshold=0.1, lora_adapters=adapters,
                )
                result = runtime.synthesize(
                    request, log_fn=print,
                    progress_callback=lambda c, t, d=done: pbar.update_absolute(d + int(c), total),
                )
                wav = result.audio.detach().float().cpu()
                if wav.dim() == 1:
                    wav = wav.unsqueeze(0)
                sr = int(result.sample_rate)
                out_sr = out_sr or sr
                wav = trim_silence(wav, sr)
                log.append(f"part{i:02d}: {wav.shape[1] / sr:5.1f}s  seed={part_seed}  refs={len(refs)}  | "
                           + text.replace("\n", " ")[:40])
                # Without a user reference, part 1 becomes the anchor voice for every later part.
                if not user_refs and anchor is None:
                    anchor = encode(wav, sr, f"anchor_{i:02d}")
                    preview = work / "anchor_preview.wav"
                    save_wav(preview, wav, sr)
                elif context_seconds > 0:
                    ctx = clean_context(wav, sr, context_seconds)
                    context = encode(ctx, sr, f"context_{i:02d}") if ctx is not None else None
                wav = wav * (0.1 / wav.pow(2).mean().add(1e-12).sqrt())
                pieces.append((wav, pause))
        finally:
            if policy == "unload_after_use":
                rmod.clear_cached_runtime()
            elif policy == "offload_after_use":
                rmod.offload_cached_runtime()

        fade = int(0.01 * out_sr)
        ramp_in, ramp_out = torch.linspace(0, 1, fade), torch.linspace(1, 0, fade)
        chunks = []
        for wav, pause in pieces:
            wav = wav.clone()
            wav[:, :fade] *= ramp_in
            wav[:, -fade:] *= ramp_out
            chunks += [wav, torch.zeros(wav.shape[0], int(pause * out_sr))]
        full = torch.cat(chunks, dim=1)
        peak = float(full.abs().max())
        if peak > 0.95:
            full = full * (0.95 / peak)
        log.append(f"total: {full.shape[1] / out_sr:.1f}s / {len(pieces)} parts")
        text_log = "\n".join(log)
        print("[IrodoriTTS Longform]\n" + text_log)

        # The voice every part was conditioned on, so it can be saved and reused later.
        checkpoint = Path(str(model_config.get("checkpoint", "")))
        voice = make_voice(
            user_refs or [anchor], preview,
            meta=ref.get("voice_meta") or {
                "source": "reference audio" if user_refs else "long-form part 1",
                "caption": caption_cfg.get("caption", None),
                "model": f"{checkpoint.parent.name}/{checkpoint.name}",
                "seed": seed_overrides.get(1, int(seed)),
            },
        )
        return ({"waveform": full.unsqueeze(0), "sample_rate": out_sr}, text_log, voice)


# ---------------------------------------------------------------------------
# Saved voices
# ---------------------------------------------------------------------------

def voice_dir():
    path = Path(folder_paths.models_dir) / "irodori_voices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_wav(path, wav, sr):
    import soundfile as sf

    sf.write(str(path), wav.detach().float().cpu().numpy().T, int(sr))


def make_voice(latents, preview=None, meta=None):
    """An IRODORI_REF_CONFIG that conditions on saved codec latents (understood by the Irodori samplers)."""
    return {
        "ref_wavs": [],
        "ref_latents": [str(p) for p in latents],
        "no_ref": False,
        "ref_normalize_db": None,
        "ref_ensure_max": True,
        "max_ref_seconds": None,
        "voice_preview": str(preview) if preview else None,
        "voice_meta": dict(meta or {}),
    }


def _safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name or "voice"


class IrodoriTTSSaveVoice:
    DESCRIPTION = (
        "Save a voice (from Long-form Sampler) to models/irodori_voices so it can be reused with Load Voice. / "
        "声を models/irodori_voices に保存し、Load Voice で次回も使えるようにします。"
    )
    CATEGORY = CATEGORY
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_as",)
    FUNCTION = "save"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "voice": ("IRODORI_REF_CONFIG", {"tooltip": "The 'voice' output of Long-form Sampler. / Long-form Sampler の voice 出力。"}),
                "name": ("STRING", {"default": "my_voice", "tooltip": "Name of the saved voice. / 保存する声の名前。"}),
                "overwrite": ("BOOLEAN", {"default": False, "tooltip":
                    "Overwrite a voice with the same name. If off, ' (2)' etc. is added. / "
                    "同じ名前の声を上書きします。オフなら「 (2)」などを付けて別名で保存します。"}),
            },
        }

    def save(self, voice, name, overwrite):
        import json
        import shutil
        from datetime import datetime

        latents = [torch.load(p, map_location="cpu", weights_only=True) for p in voice.get("ref_latents") or []]
        if not latents:
            raise ValueError("This voice has no saved latent. Connect the 'voice' output of Long-form Sampler.")
        # Latents are (frames, dim) with dim 32 or 128; concatenate clips along time like the Irodori runtime.
        latents = [z.squeeze(0) if z.dim() == 3 else z for z in latents]
        latents = [z.T if z.shape[-1] not in (32, 128) and z.shape[0] in (32, 128) else z for z in latents]
        latent = torch.cat(latents, dim=0).contiguous()

        base = _safe_name(name)
        stem, n = base, 2
        while not overwrite and (voice_dir() / f"{stem}.pt").exists():
            stem, n = f"{base} ({n})", n + 1
        target = voice_dir() / f"{stem}.pt"
        torch.save(latent, target)

        preview = voice.get("voice_preview")
        if preview and Path(preview).exists():
            shutil.copyfile(preview, target.with_suffix(".wav"))
        meta = dict(voice.get("voice_meta") or {})
        meta.update({"name": stem, "saved_at": datetime.now().isoformat(timespec="seconds"),
                     "latent_frames": int(latent.shape[0])})
        target.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        message = f"saved voice: {stem}  ({target})"
        print(f"[IrodoriTTS Longform] {message}")
        return {"ui": {"text": [message]}, "result": (stem,)}


class IrodoriTTSLoadVoice:
    DESCRIPTION = (
        "Load a voice saved with Save Voice. Connect it to 'ref_config' of Long-form Sampler (or the Irodori Sampler). / "
        "Save Voice で保存した声を読み込みます。Long-form Sampler（または Irodori Sampler）の ref_config につなぎます。"
    )
    CATEGORY = CATEGORY
    RETURN_TYPES = ("IRODORI_REF_CONFIG", "STRING")
    RETURN_NAMES = ("voice", "info")
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        names = sorted(p.stem for p in voice_dir().glob("*.pt"))
        return {"required": {"voice_name": (names or ["(no saved voices)"], {
            "tooltip": "Voices in models/irodori_voices. / models/irodori_voices にある声。"})}}

    @classmethod
    def IS_CHANGED(cls, voice_name):
        path = voice_dir() / f"{voice_name}.pt"
        return path.stat().st_mtime if path.exists() else voice_name

    def load(self, voice_name):
        import json

        path = voice_dir() / f"{voice_name}.pt"
        if not path.exists():
            raise FileNotFoundError(f"Saved voice not found: {path}. Save one with 'IrodoriTTS Save Voice' first.")
        meta_path, wav_path = path.with_suffix(".json"), path.with_suffix(".wav")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        info = "\n".join(f"{k}: {v}" for k, v in meta.items() if v not in (None, ""))
        return (make_voice([path], wav_path if wav_path.exists() else None, meta), info or voice_name)


NODE_CLASS_MAPPINGS = {
    "IrodoriLongform.Sampler": IrodoriTTSLongformSampler,
    "IrodoriLongform.SaveVoice": IrodoriTTSSaveVoice,
    "IrodoriLongform.LoadVoice": IrodoriTTSLoadVoice,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "IrodoriLongform.Sampler": "IrodoriTTS Long-form Sampler",
    "IrodoriLongform.SaveVoice": "IrodoriTTS Save Voice",
    "IrodoriLongform.LoadVoice": "IrodoriTTS Load Voice",
}
