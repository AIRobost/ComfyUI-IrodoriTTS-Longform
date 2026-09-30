# ComfyUI-IrodoriTTS-Longform

[English](README.md) | [日本語](README.ja.md) | **简体中文** | [한국어](README.ko.md)

适用于 ComfyUI 的日语长文本语音合成节点。
粘贴整段台本，本节点会使用 [Irodori-TTS](https://github.com/Aratako/Irodori-TTS) 分段生成，并 **从头到尾保持同一个音色**，最后合并为一条音频。

基于 [comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) 构建。

## 为什么需要它

Irodori-TTS 生成短句非常自然，但长台本必须分段生成。
如果各段分别生成（即使固定 seed），音色、音量和表演都会在段与段之间发生偏移，拼接处听起来很不自然。
本节点让所有段落使用同一个参考音色，并统一响度和停顿，让整体听起来像一段连续的表演。

## 工作原理

```
台本
  │  按 "---" 行（或段落）切分，并转换舞台提示 / 表情符号
  ▼
第1段 ──► 生成 ──► 成为之后所有段落的「锚点音色」
第2段 ──► 生成（参考: 锚点）
第3段 ──► 生成（参考: 锚点）
  …
  ▼
去除静音 ▸ 统一响度 ▸ 插入停顿 ▸ 合并  ──►  一条音频
```

- **锚点**：第1段（或你提供的参考音频）固定音色，避免段与段之间音色漂移。
- **平滑衔接**：去除静音、统一响度、插入停顿，让拼接处不明显。
- 参考以编解码器潜变量的形式传入，无需额外的音频解码库。

> 为什么不把上一段作为参考？我们试过：把生成的音频再作为参考，会不断累积细小的瑕疵，
> 几段之后句尾会变得沙哑。该功能仍作为实验选项（`context_seconds`）保留，但默认的仅锚点模式最稳定。

## 环境要求

- ComfyUI
- [comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) 及其依赖
- Irodori-TTS v4.1 模型，例如
  [Aratako/Irodori-TTS-v4.1-Small](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small) 或
  [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime)

测试环境：Windows 11 / ComfyUI 0.38 / RTX 2060 (6 GB) / comfy-IrodoriTTS `60b5724`。
无需额外的 Python 依赖。

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/AIRobost/ComfyUI-IrodoriTTS-Longform.git
```

重启 ComfyUI 后，`IrodoriTTS Longform` 分类中会出现 **IrodoriTTS Long-form Sampler**。

## 使用方法

打开 [`workflows/irodori_longform_example.json`](workflows/irodori_longform_example.json)，或按如下方式连接：

```
IrodoriTTS Model Loader ──► IrodoriTTS Long-form Sampler ──► Save Audio
IrodoriTTS VoiceDesign Config ──┘         └──► (log) Preview as Text
IrodoriTTS Reference Audio（可选） ──┘
```

### 台本格式

**直接粘贴台本即可。** 节点会自动切分：按空行分隔的段落，每段最多合并 `max_chars` 个字符；过长的段落会在换行和句末（。！？）处继续切分。没有空行的台本或小说文本也可以直接使用。

如果想自己决定场景的分隔位置（以及停顿长度），请加入只有 `---` 的行：

```
第一段台词。
可以跨越多行。
--- 1.2
第二段。上面的 "--- 1.2" 表示在这一段之前停顿 1.2 秒。
---
第三段（使用默认停顿）。
```

`---` 之间的内容会保持为一段（仅当超过 `max_chars` 的 2 倍时才会继续切分）。
每段 60–120 个日文字符（约 10–20 秒）效果最佳。

### 输入参数

| 输入 | 说明 |
|---|---|
| `script` | 完整台本。可使用 Irodori-TTS 的表情符号标注（🤭 😮‍💨 ⏸️ 👂 等）。 |
| `seed` | 基础 seed。第 N 段使用 `seed + N - 1`。 |
| `split_mode` | `auto`（有 `---` 则按其切分，否则自动切分）/ `separator (---)` / `paragraph`（始终自动切分） |
| `max_chars` | 自动切分时每段的目标最大字符数。 |
| `pause_seconds` | 段与段之间的默认停顿。 |
| `context_seconds` | 实验功能。把上一段（去除句尾）作为第二参考的秒数。**推荐 0（仅锚点）**，数值较大时句尾可能变得沙哑。 |
| `num_steps` | 每段的采样步数。 |
| `clean_text` | 将不支持的表情符号以及 `(sigh)` / `（はぁ…）` 等舞台提示转换为 Irodori 表情符号，并在缺少句末标点的日语行末补上 `。`（没有句末标点时句尾容易变得含糊）。 |
| `part_seeds` | 重新生成指定段落，例如 `3:1234, 5:99`。其后的段落也会随之变化。 |
| `voice_design_config` | （可选）描述音色的提示文本，所有段落共用。 |
| `ref_config` | （可选）用于声音克隆的参考音频，作为锚点音色使用。 |
| `lora_stack`, `cfg_config` | （可选）与原始 Sampler 相同。 |

输出：`audio`（合并后的音频）和 `log`（各段的时长 / seed，以及 `clean_text` 所做的修改）。

### 提示

- 不支持 bf16 的显卡（如 RTX 20 系列）请在 Model Loader 中将 `model_precision` / `codec_precision` 设为 **fp32**。
- 对某一段不满意时，可在日志中确认编号，并通过 `part_seeds` 重新生成。
- Irodori-TTS 中的 🥤 表示「吞咽声」，而不是饮料。

## 合理使用

请遵守 Irodori-TTS 模型的使用限制：

- 未经本人明确同意，**不得**克隆或模仿任何真实人物（声优、名人、公众人物等）的声音。
- **不得**制作以误导他人或传播虚假信息为目的的深度伪造或合成语音。
- 公开发布生成的音频时，请注明其为 AI 生成。

## 致谢

- [Aratako/Irodori-TTS](https://github.com/Aratako/Irodori-TTS) — 语音合成模型（MIT）
- [kjranyone/comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) — 本项目所依赖的 ComfyUI 节点（MIT）
- [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime) — 动漫风格微调模型（MIT）
- [facebookresearch/dacvae](https://github.com/facebookresearch/dacvae) — 音频编解码器

## 许可证

[MIT](LICENSE) © 2026 AIRobost
