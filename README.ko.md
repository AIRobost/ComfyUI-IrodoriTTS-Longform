# ComfyUI-IrodoriTTS-Longform

[English](README.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | **한국어**

ComfyUI용 일본어 장문 음성 합성 노드입니다.
대본 전체를 붙여 넣으면 [Irodori-TTS](https://github.com/Aratako/Irodori-TTS)로 파트별로 생성하면서 **처음부터 끝까지 같은 목소리로** 하나의 오디오로 합칩니다.

[comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS)를 기반으로 만들었습니다.

## 왜 필요한가

Irodori-TTS는 짧은 대사에서는 매우 자연스럽지만, 긴 대본은 나누어 생성해야 합니다.
파트를 따로따로 생성하면 (seed를 고정해도) 목소리, 음량, 연기가 파트마다 달라져 이음매가 어색하게 들립니다.
이 노드는 모든 파트의 목소리를 같은 기준으로 맞추고 음량과 쉼도 정리해, 하나의 이어지는 연기처럼 들리게 합니다.

## 동작 방식

```
대본
  │  "---" 줄(또는 문단)로 나누고, 지문 / 이모지를 변환
  ▼
파트 1 ──► 생성 ──► 이후 모든 파트의 「기준 목소리(앵커)」가 됨
파트 2 ──► 생성 (참조: 앵커)
파트 3 ──► 생성 (참조: 앵커)
  …
  ▼
무음 제거 ▸ 음량 맞춤 ▸ 쉼 삽입 ▸ 연결  ──►  하나의 오디오
```

- **앵커**: 파트 1(또는 사용자의 참조 음성)이 목소리를 고정하므로 파트마다 목소리가 흔들리지 않습니다.
- **자연스러운 이음매**: 무음 제거, 음량 맞춤, 쉼 삽입으로 이음매가 드러나지 않게 합니다.
- 참조는 코덱 잠재 표현으로 전달하므로 추가 오디오 라이브러리가 필요 없습니다.

> 직전 파트를 참조로 쓰지 않는 이유: 시험해 보니 생성된 오디오를 다시 참조로 쓰면 작은 잡음이 쌓여
> 몇 파트 뒤에는 문장 끝이 쉰 목소리처럼 됩니다. 실험 옵션(`context_seconds`)으로 남겨 두었지만,
> 기본값인 앵커 전용이 가장 안정적입니다.

## 요구 사항

- ComfyUI
- [comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) 및 그 의존 패키지
- Irodori-TTS v4.1 체크포인트 (예:
  [Aratako/Irodori-TTS-v4.1-Small](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small),
  [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime))

테스트 환경: Windows 11 / ComfyUI 0.38 / RTX 2060 (6 GB) / comfy-IrodoriTTS `60b5724`.
추가 Python 패키지는 필요 없습니다.

## 설치

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/AIRobost/ComfyUI-IrodoriTTS-Longform.git
```

ComfyUI를 재시작하면 `IrodoriTTS Longform` 카테고리에 **IrodoriTTS Long-form Sampler**가 추가됩니다.

## 사용법

[`workflows/irodori_longform_example.json`](workflows/irodori_longform_example.json)을 열거나 다음과 같이 연결합니다.

```
IrodoriTTS Model Loader ──► IrodoriTTS Long-form Sampler ──► Save Audio
IrodoriTTS VoiceDesign Config ──┘         └──► (log) Preview as Text
IrodoriTTS Reference Audio (선택) ──┘
```

### 대본 형식

```
첫 번째 파트입니다.
여러 줄에 걸쳐 써도 됩니다.
--- 1.2
두 번째 파트. 위의 "--- 1.2"는 이 파트 앞에 1.2초의 쉼을 넣는다는 뜻입니다.
---
세 번째 파트 (기본 쉼).
```

`---` 줄이 없으면 빈 줄로 구분된 문단을 파트당 최대 `max_chars`자까지 묶습니다.
파트당 일본어 60–120자(약 10–20초)가 가장 안정적입니다.

### 입력

| 입력 | 설명 |
|---|---|
| `script` | 대본 전체. Irodori-TTS의 이모지 주석(🤭 😮‍💨 ⏸️ 👂 등)을 사용할 수 있습니다. |
| `seed` | 기준 seed. 파트 N은 `seed + N - 1`을 사용합니다. |
| `split_mode` | `auto`(`---`가 있으면 그것으로, 없으면 문단) / `separator (---)` / `paragraph` |
| `max_chars` | 문단을 묶을 때 파트당 최대 글자 수. |
| `pause_seconds` | 파트 사이의 기본 쉼. |
| `context_seconds` | 실험 기능. 직전 파트(문장 끝 제외)를 두 번째 참조로 추가하는 초 수. **0(앵커만)을 권장**하며, 값이 크면 문장 끝이 쉰 소리가 될 수 있습니다. |
| `num_steps` | 파트별 샘플링 스텝 수. |
| `clean_text` | 지원되지 않는 이모지와 `(sigh)` / `（はぁ…）` 같은 지문을 Irodori 이모지로 변환합니다. |
| `part_seeds` | 특정 파트 다시 생성. 예: `3:1234, 5:99`. 그 뒤의 파트도 함께 바뀝니다. |
| `voice_design_config` | (선택) 목소리를 설명하는 캡션. 모든 파트에 공통 적용. |
| `ref_config` | (선택) 음성 복제용 참조 음성. 앵커 목소리로 사용됩니다. |
| `lora_stack`, `cfg_config` | (선택) 원래 Sampler와 같습니다. |

출력: `audio`(연결된 오디오)와 `log`(각 파트의 길이 / seed, `clean_text`로 바뀐 내용).

### 팁

- bf16을 지원하지 않는 GPU(RTX 20 시리즈 등)에서는 Model Loader의 `model_precision` / `codec_precision`을 **fp32**로 설정하세요.
- 마음에 들지 않는 파트는 로그에서 번호를 확인한 뒤 `part_seeds`로 다시 생성할 수 있습니다.
- Irodori-TTS의 🥤는 음료가 아니라 「침 삼키는 소리」를 뜻합니다.

## 윤리적 사용

Irodori-TTS 모델의 이용 제한을 지켜 주세요.

- 본인의 명시적인 동의 없이 실존 인물(성우, 유명인, 공인 등)의 목소리를 복제하거나 흉내 내지 **마세요**.
- 다른 사람을 속이거나 허위 정보를 퍼뜨리기 위한 딥페이크나 합성 음성을 만들지 **마세요**.
- 생성한 오디오를 공개할 때는 AI로 생성했음을 밝혀 주세요.

## 크레딧

- [Aratako/Irodori-TTS](https://github.com/Aratako/Irodori-TTS) — 음성 합성 모델 (MIT)
- [kjranyone/comfy-IrodoriTTS](https://github.com/kjranyone/comfy-IrodoriTTS) — 이 프로젝트가 기반으로 하는 ComfyUI 노드 (MIT)
- [phasefield-audio/Irodori-TTS-v4.1-Anime](https://huggingface.co/phasefield-audio/Irodori-TTS-v4.1-Anime) — 애니메이션풍 파인튜닝 모델 (MIT)
- [facebookresearch/dacvae](https://github.com/facebookresearch/dacvae) — 오디오 코덱

## 라이선스

[MIT](LICENSE) © 2026 AIRobost
