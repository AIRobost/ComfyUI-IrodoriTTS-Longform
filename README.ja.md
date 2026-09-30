# ComfyUI-IrodoriTTS-Longform

[English](README.md) | **日本語** | [简体中文](README.zh-CN.md) | [한국어](README.ko.md)

ComfyUI 用の、日本語の長文読み上げノードです。
台本をまるごと貼ると、[Irodori-TTS](https://github.com/Aratako/Irodori-TTS) でパートごとに生成しながら **最初から最後まで同じ声のまま**、1本の音声につなげます。

[comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) の上に作っています。

## なぜ作ったか

Irodori-TTS は短いセリフなら自然ですが、長い台本は分けて生成する必要があります。
パートを別々に作ると（seed を固定しても）声・音量・演技がパートごとにズレて、つなぎ目で違和感が出ます。
このノードは全パートの声を同じ基準にそろえ、音量と間も整えて、ひと続きの演技に聞こえるようにします。

## しくみ

```
台本
  │  「---」の行（または段落）で分割、ト書き・絵文字を調整
  ▼
パート1 ──► 生成 ──► 以降すべてのパートの「基準の声（アンカー）」になる
パート2 ──► 生成（参照: アンカー）
パート3 ──► 生成（参照: アンカー）
  …
  ▼
無音カット ▸ 音量合わせ ▸ 間を挿入 ▸ 連結  ──►  1本の音声
```

- **アンカー**: パート1（または参照音声）で声を固定するので、パートごとに声がブレません。
- **つなぎ目をそろえる**: 無音カット・音量合わせ・間の挿入で、つなぎ目が目立たないようにします。
- 参照はコーデックの潜在表現で渡すため、追加の音声ライブラリは不要です。

> 直前のパートを参照に戻さない理由: 試したところ、生成した音声を参照に使うと小さな乱れが積み重なり、
> 数パート後には語尾がかすれるようになりました。実験的なオプション（`context_seconds`）として残していますが、
> 既定のアンカーのみが最も安定します。

## 必要なもの

- ComfyUI
- [comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) とその依存パッケージ
- Irodori-TTS v4.1 のチェックポイント（例:
  [Aratako/Irodori-TTS-v4.1-Small](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small)、
  [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime)）

動作確認: Windows 11 / ComfyUI 0.38 / RTX 2060 (6 GB) / comfy-IrodoriTTS `60b5724`。
追加の Python パッケージは不要です。

## インストール

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/AIRobost/ComfyUI-IrodoriTTS-Longform.git
```

ComfyUI を再起動すると、`IrodoriTTS Longform` カテゴリに **IrodoriTTS Long-form Sampler** が追加されます。

## 使い方

[`workflows/irodori_longform_example.json`](workflows/irodori_longform_example.json) を開くか、次のようにつなぎます。

```
IrodoriTTS Model Loader ──► IrodoriTTS Long-form Sampler ──► Save Audio
IrodoriTTS VoiceDesign Config ──┘         └──► (log) Preview as Text
IrodoriTTS Reference Audio（任意） ──┘
```

### 台本の書き方

**台本を貼るだけでOKです。** 自動で分割します。空行で区切られた段落を `max_chars` 文字ずつまとめ、長すぎる段落は改行や文の終わり（。！？）で区切ります。空行のない台本や小説の文章もそのまま使えます。

場面の区切り（と間の長さ）を自分で決めたいときは、`---` だけの行を入れます。

```
最初のパート。
複数行にまたがってもOKです。
--- 1.2
2つ目のパート。上の「--- 1.2」は、この前に1.2秒の間を入れる指定です。
---
3つ目のパート（間は既定値）。
```

`---` で区切ったブロックはそのまま1パートになります（`max_chars` の2倍を超える場合だけ、さらに分割します）。
1パートは 60〜120 字（10〜20 秒）くらいが安定します。

### 入力

| 入力 | 説明 |
|---|---|
| `script` | 台本全体。Irodori-TTS の絵文字注釈（🤭 😮‍💨 ⏸️ 👂 など）が使えます。 |
| `seed` | 基準の seed。パートN は `seed + N - 1` を使います。 |
| `split_mode` | `auto`（`---` があればそれ、なければ自動分割）/ `separator (---)` / `paragraph`（常に自動分割） |
| `max_chars` | 自動分割での、1パートの最大文字数の目安。 |
| `pause_seconds` | パート間の間（既定値）。 |
| `context_seconds` | 実験的機能。直前パート（語尾を除く）を2つ目の参照として足す秒数。**0（アンカーのみ）を推奨**。大きくすると語尾がかすれることがあります。 |
| `num_steps` | パートごとのサンプリングステップ数。 |
| `clean_text` | 未対応の絵文字や `（はぁ…）` `(sigh)` などのト書きを、Irodori の絵文字に変換します。 |
| `part_seeds` | 特定パートの作り直し。例: `3:1234, 5:99`。そのパートを引き継ぐ後ろのパートも変わります。 |
| `voice_design_config` | （任意）声の指定（キャプション）。全パート共通。 |
| `ref_config` | （任意）声クローン用の参照音声。アンカーの声として使います。 |
| `lora_stack`, `cfg_config` | （任意）元の Sampler と同じです。 |

出力: `audio`（連結した音声）と `log`（各パートの秒数・seed、`clean_text` で変えた内容）。

### コツ

- bf16 非対応の GPU（RTX 20 シリーズなど）では、Model Loader の `model_precision` / `codec_precision` を **fp32** にしてください。
- 気に入らないパートは、ログで番号を確認して `part_seeds` で作り直せます。
- Irodori-TTS の 🥤 は「唾を飲み込む音」で、飲み物の意味ではありません。

## 倫理的な利用について

Irodori-TTS のモデルの制限に従ってください。

- 本人の明確な同意なしに、実在の人物（声優・有名人・公人など）の声をクローン・模倣しないでください。
- 人をだます目的のディープフェイクや、誤情報の拡散に使わないでください。
- 生成した音声を公開するときは、AI による生成であることを明記してください。

## クレジット

- [Aratako/Irodori-TTS](https://github.com/Aratako/Irodori-TTS) — 音声合成モデル（MIT）
- [kjranyone/comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) — 本ノードが利用している ComfyUI ノード（MIT）
- [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime) — アニメ調ファインチューン（MIT）
- [facebookresearch/dacvae](https://github.com/facebookresearch/dacvae) — 音声コーデック

## ライセンス

[MIT](LICENSE) © 2026 AIRobost
