# HEARU MATE（听会儿）

独立的 Windows 桌面会议纪要应用，英文品牌名为 HEARU MATE，中文名为
“听会儿”。项目使用 PySide6，不包含 Web、Flask、
SSE 或本地 HTTP 服务，也不依赖 DocAgent 的 Agent、视觉、订单与评测模块。

## 当前开发阶段

第一轮已完成：

- PySide6 主窗口、浅色桌面布局、历史会议侧栏和设置页。
- QThread 录制工作线程，以及 partial、final、status、completed、error 信号链。
- Partial 在同一个列表项中增长，Final 后固定并创建下一段。
- SQLite 历史会议、原始文本与校对文本分离保存。
- JSON 和 Markdown 输出。
- 会后可为 Speaker 标签设置姓名；原始标签保留在 JSON，Markdown 使用姓名
  重新生成。
- 历史会议可使用同一套 OpenAI-compatible API 生成结构化 AI 摘要，摘要持久化
  到 SQLite，并可随 Markdown 一并导出。
- 首次启动 API Key 强提醒、项目 .env 持久化和设置页更换。
- 从 DocAgent 独立迁移的音频、VAD、ASR、说话人、对齐、校对和存储核心。

当前入口已切换为真实本地链路。启动后异步枚举 Windows WASAPI Loopback
输出设备；点击“开始纪要”后，工作线程依次加载 Silero VAD、Paraformer
Streaming 和说话人模型，再打开所选输出设备进行实时识别。GUI 主线程不执行
录音、推理、说话人区分或会后校对。

### Windows COM 与 SoundCard

SoundCard 0.4.6 在首次导入时创建模块级 COM helper。应用会先创建
QApplication，让 GUI 主线程保持 STA，再于同一主线程预加载 SoundCard；
设备枚举线程和录音
线程仍各自调用 CoInitializeEx，并在同一线程内配对 CoUninitialize。录音线程
会保持 COM 有效直到 recorder context、音频设备和模型服务全部释放。
RPC_E_CHANGED_MODE 表示线程已有其他 apartment mode，此时不会重复释放。
GUI 与录音线程之间只传递设备 ID 和名称，不共享 SoundCard COM 对象。

## 环境

使用现有 Conda 环境：

    conda activate D:\apps\anaconda\envs\meeting_onnx

若 conda activate 在当前终端不可用，可直接使用环境中的 Python：

    & "D:\apps\anaconda\envs\meeting_onnx\python.exe" -m pip install -r requirements.txt

requirements.txt 只声明运行库，不包含或下载任何模型。模型文件由用户单独
维护在 D:\models\sherpa-onnx。

## 开发模式启动

在项目目录执行：

    & "D:\apps\anaconda\envs\meeting_onnx\python.exe" -m desktop.app

点击“开始纪要”会加载本地模型并捕获所选 Windows 输出设备。结束后依次执行
说话人区分、可选 AI 校对和保存，结果写入 data\meetings，历史列表会刷新。

## 测试

    & "D:\apps\anaconda\envs\meeting_onnx\python.exe" -m unittest discover -s tests -v

单元测试使用临时目录和模拟服务，不访问网络、不采集音频。真实模型兼容性
需使用单独的本地 smoke test 验证。

## 数据与隐私

- 默认不保存原始音频。
- 录制期间，说话人分析所需的 16 kHz 单声道音频写入 Windows 系统临时
  文件，避免长会议整段堆积在 Python 内存；停止、失败或进程退出时由文件
  句柄自动删除，不作为会议文件保留。
- 每个 Final ASR 片段会立即检查点写入 SQLite。若程序意外退出，已经完成的
  片段仍可从标记为 interrupted 的会议中查看；正常结束时会由说话人对齐和
  AI 校对后的最终片段替换。
- 用户输入的 API Key 保存在本项目 .env，并加载到进程环境变量
  DEEPSEEK_API_KEY；设置页输入新值时原子替换。
- .gitignore 排除 .env、Key、数据库、会议输出和音频文件；.env.example
  只包含空变量名，不包含真实 Key。
- 校对按批次执行并对异常响应重试一次；单批失败只回退该批原文。界面会明确
  标记 success、partial 或 fallback，不再把校对失败显示成普通成品。
- 校对失败或部分失败的历史会议会显示“重新 AI 校对”按钮。重新校对在独立
  QThread 中运行，保留 raw_text、说话人命名和已有摘要，并重新生成 JSON 与
  Markdown；新的失败记录会保存可安全展示的错误原因。
- AI 摘要在独立 QThread 中生成；失败不会覆盖原始纪要或已有摘要。
- 应用不读取 DocAgent 的 agent/.env。

## 目录

    MeetingRecorderDesktop/
    ├── meeting/       # 独立会议核心
    ├── desktop/       # PySide6 GUI 与 QThread 工作线程
    ├── assets/
    ├── config/
    ├── data/meetings/
    ├── tests/
    ├── requirements.txt
    └── README.md

模型采用延迟初始化：只查看历史或修改设置时不会占用模型内存；每次会议结束
后会释放音频设备和模型资源。
