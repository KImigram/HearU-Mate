# Third-party notices

HearU Mate is licensed under Mozilla Public License 2.0. Third-party libraries and
model files remain subject to their own licenses. This document is attribution
information and does not replace those license texts.

## Local models

Model files are not stored in this repository and are not downloaded by the
application.

| Component | Upstream | License | Notes |
| --- | --- | --- | --- |
| Silero VAD | [snakers4/silero-vad](https://github.com/snakers4/silero-vad) | MIT | ONNX model used for voice activity detection. |
| Streaming Paraformer | [iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online](https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online) | Apache-2.0 | Streaming Chinese/English ASR model; INT8 ONNX files are loaded through sherpa-onnx. |
| pyannote segmentation 3.0 | [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) | MIT | Segmentation stage of post-recording speaker diarization. |
| WeSpeaker CN-Celeb ResNet34-LM | [Wespeaker/wespeaker-cnceleb-resnet34-LM](https://huggingface.co/Wespeaker/wespeaker-cnceleb-resnet34-LM) | Apache-2.0 | Speaker-embedding stage of post-recording diarization. The local `wespeaker-cnceleb-resnet34-LM-sherpa.onnx` keeps the upstream weights and adds sherpa-onnx model metadata required by the runtime. |

Some ONNX artifacts are distributed through the
[sherpa-onnx model releases](https://github.com/k2-fsa/sherpa-onnx/releases).
Before redistributing any model, verify and include the exact license and
attribution files shipped with that model artifact.

## Principal runtime dependencies

The authoritative dependency list is `requirements.txt`. Principal runtime
components include:

| Component | License family | Purpose |
| --- | --- | --- |
| PySide6 / Shiboken6 | LGPL-3.0-only, GPL, or commercial terms depending on distribution | Windows desktop GUI |
| sherpa-onnx | Apache-2.0 | ONNX speech inference |
| SoundCard | BSD-3-Clause | Windows WASAPI loopback capture |
| NumPy | BSD-style and bundled third-party notices | Audio and numerical processing |
| psutil | BSD-3-Clause | Process and resource handling |
| OpenAI Python SDK | Apache-2.0 | OpenAI-compatible correction and summary requests |
| HTTPX / HTTPCore | BSD-3-Clause | HTTP transport |

Transitive dependencies may carry additional notices. A future binary release
must ship the complete license files collected from the exact locked dependency
versions used to build that release. Consult each upstream distribution for the
authoritative terms.

## No endorsement

The names of upstream projects and model authors are used only for attribution.
They do not imply endorsement of HearU Mate.
