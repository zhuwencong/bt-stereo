# 给 AI 助手的安装指令

> 如果你的用户把这个仓库链接发给你、让你帮他装好，请照下面的步骤做。
> 目标：在这台 **Windows** 电脑上把工具跑起来，让两只音箱分别输出左右声道。

## 0. 先确认环境（只读，不要改动任何东西）

- 必须是 **Windows 10 / 11**：程序依赖 WASAPI 的 COM 接口，macOS / Linux 上无法运行。
  先执行 `ver` 或 `[System.Environment]::OSVersion` 确认；不是 Windows 就直接告诉用户不支持。
- 需要 **Python 3.10+**：`python --version`
- 没装 Python 的话，让用户去 <https://www.python.org/downloads/> 下载，
  **安装时必须勾选 "Add python.exe to PATH"**（这一步只能用户自己点，你不能代劳）。

## 1. 拿到代码

```bat
git clone https://github.com/zhuwencong/bt-stereo.git
cd bt-stereo
```

没有 git 就让用户下载 ZIP 解压（GitHub 绿色 `Code` → `Download ZIP`；
国内网络用 Gitee：<https://gitee.com/xingchencong/bt-stereo>）。

## 2. 装依赖

```bat
python -m pip install numpy comtypes
```

国内网络慢时加镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`

只需要这两个包，**不需要** soundcard / sounddevice / VB-Cable / Voicemeeter 之类的虚拟声卡。

## 3. 先体检，再动手（重要）

```bat
python -m bt_stereo --cli doctor
```

这是只读检查，不会修改任何系统设置。看最后的「结论」行：

| 结论 | 含义 | 下一步 |
| --- | --- | --- |
| ✔ 有 2 只蓝牙音箱同时在线 | 环境就绪 | 继续第 4 步 |
| △ 只连上了 1 只 | 第二只没连上 | 让用户在 设置 → 蓝牙和设备 里把另一只点「连接」，等 5 秒，再跑一次 doctor |
| ✘ 没有任何蓝牙音箱连着 | 都没连 | 先配对/连接，再跑 doctor |
| ✘ 蓝牙适配器没有正常工作 | 驱动/禁用问题 | 让用户去设备管理器检查；这一步不要自己动驱动 |

`doctor` 还会打印每只已配对音箱的 CO D 类别、蓝牙规范、上次连接时间，可以据此判断用户到底有几只可用的音频设备。

## 4. 启动

```bat
启动.bat
```

或者 `python -m bt_stereo`（不加 `--cli` 打开图形界面）。

界面上只需要用户选两件事：**左声道音箱**、**右声道音箱**。
「音源」保持默认即可——程序在点「开始」时会自动把 Windows 默认播放设备切到音源端点，
停止时自动切回，所以用户不需要去声音设置里手动改任何东西。

也可以纯命令行（适合远程指导）：

```bat
python -m bt_stereo --cli run --left "Q6" --right "DOME 2" --source "扬声器 (ToDesk Virtual Audio)"
```

## 5. 验证

- 界面「试音」按钮：左声道 440Hz、右声道 660Hz，各 1.2 秒。两只都响 = 成功。
- 命令行自检：`python -m bt_stereo --cli test`（枚举设备 + 播 1.5 秒测试音并回环录回来）
- 分离正确性：`python tests\test_split.py`（左箱应测出 ~1000Hz，右箱 ~3000Hz，串音接近 0）

## 关键概念（照这个判断，别瞎试）

- **音源 ≠ 左/右输出**：音源是"音乐实际播放到的端点"，左右输出是两只音箱。选成同一个会自激。
- **自动切换默认设备**：程序用 `IPolicyConfig` 改系统默认输出，停止时恢复原值。
  如果用户发现系统声音去了别处，点一下「停止」就恢复了。
- **两只箱子型号不同完全可以**；**有线 + 蓝牙混合也可以**，用「延迟补偿」把快的那侧往后推
  （蓝牙大约 150~250ms，所以有线那侧填 200ms 起步）。
- **延迟补偿怎么调**：放一首有人声的歌，听起来"慢半拍"的那只加 20~80ms，直到声音重合。
- **蓝牙双连**需要适配器支持同时两条 A2DP 链路。Intel AX200/AX201/AX210 一般可以；
  Realtek 模块常常只允许一条。两只都连不上时，优先建议用户换 USB 蓝牙 5.3 适配器，
  或者用音箱自带的 TWS 功能（同型号音箱才支持）。
- **采样率不同**（音源 48kHz、音箱 44.1kHz）会自动重采样，不用管。

## 如果你需要改代码

纯 Python，只用 `numpy` + `comtypes`，没有第三方音频库；COM 接口是手写 ctypes 封装的。

| 文件 | 作用 |
| --- | --- |
| `bt_stereo/wasapi.py` | WASAPI 封装：设备枚举、播放流、回环捕获、默认设备切换 |
| `bt_stereo/engine.py` | 拆分引擎：环形缓冲 + 双读取器 + 漂移补偿 + 掉线重连 |
| `bt_stereo/doctor.py` | 蓝牙体检（只读注册表 + cfgmgr32） |
| `bt_stereo/gui.py` | tkinter 界面 |
| `tests/` | 闭环测试，`test_split.py` 最有参考价值 |

改完建议跑一遍 `python tests\test_split.py`（需要至少 3 个播放端点）和
`python tests\test_glitch.py 15`（卡顿检测，断流应 < 3%）。

## 不要做的事

- 不要卸载 / 重装用户的蓝牙设备或驱动。
- 不要写注册表的蓝牙键值（`BTHPORT\Parameters\Devices` 只读是有意为之）。
- 不要擅自设置开机自启、也不要改动用户其它音频软件。
- 不要把 `settings.json` 提交进仓库（里面是用户的设备 id，已在 `.gitignore` 里）。

## English (for non-Chinese agents)

This is a Windows-only tool that splits the left/right channels of system audio into two
separate output devices (e.g. two Bluetooth speakers) using WASAPI loopback. Requirements:
Windows 10+, Python 3.10+, `numpy`, `comtypes`. Run `python -m bt_stereo --cli doctor`
to check the Bluetooth setup, then `python -m bt_stereo` for the GUI (or
`python -m bt_stereo --cli run --left <name> --right <name> --source <name>`).
The app temporarily switches the Windows default playback device to its source endpoint
and restores it on stop. Do not uninstall drivers or modify Bluetooth registry keys.
