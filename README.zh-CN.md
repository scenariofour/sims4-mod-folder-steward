[English](./README.md) | [**简体中文**](./README.zh-CN.md)

# Sims 4 Mod Folder Steward

一个在本机运行、面向普通玩家的桌面工具，用来检查、规划、备份、执行和撤销《模拟人生 4》Mods 文件夹改动。

> **状态：** v0.1 beta 候选版。任何文件管理工具第一次使用时，都建议先用 Mods 副本测试。

## 极简流程

PySide6 程序只有一个窗口和三个页面：

1. **开始：** 自动寻找常用 Mods 文件夹。拖入 Mods、可选 Inbox、ZIP、`.package` 或
   `.ts4script`，选择界面和外层分类语言，然后点击“检查我的 Mods”。
2. **检查结果：** 只看“可以安全处理”“需要你同意”“暂时不动”三组；技术证据放在可展开的高级详情。
3. **确认与恢复：** 查看数量，可选完整 Mods 备份，一次批准整份 Plan；完成后可以打开结果或撤销。

当前未知文件保持原位置；Inbox 未知文件留在本次待检查区，不会安装进 Mods。

## 安全承诺

- 每份 Plan 前先只读扫描
- CLI 默认只预览
- 完全相同的重复副本可移入可恢复的本次备份
- 安装、替换和整理改动必须整体批准
- 替换前先把当前原文件移入隔离备份
- 可选完整 Mods 备份，并显示预计空间
- 每项操作和 Undo 前重新检查路径与哈希
- 永不永久删除，GUI 也没有删除备份功能
- 永不读写 `Saves`
- 不联网，不内置登录、AI API、MCP、自动下载或插件系统

## 从源码运行

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows：.venv\Scripts\activate
python -m pip install -e .
s4mod-gui
```

终端和 Agent 用户仍可使用 CLI：

```bash
s4mod scan --mods "/path/to/Mods"
s4mod run --mods "/path/to/Mods" --inbox "/path/to/Inbox"
s4mod run --mods "/path/to/Mods" --inbox "/path/to/Inbox" --apply
s4mod undo --mods "/path/to/Mods" --run "/path/to/run"
```

参见：[开始使用](./docs/zh-CN/开始使用.md)与 [Agent 说明](./AGENTS.md)。

## 结合 AI 检查

GUI 只导出一个 `AI_CHECK_*.zip`，里面是匿名报告和安全 Prompt。把这一份 ZIP 交给 AI
助手即可；程序自身不会连接任何 AI 服务。Agent 可以使用自己的浏览工具，但候选下载仍必须回到本地
Planner 和 Executor 验证。

AI ZIP 不包含真实 Mod 内容。参见：[结合 AI 使用](./docs/zh-CN/结合AI使用.md)。

## 构建桌面程序

Windows 和 macOS 必须分别在对应系统构建：

```bash
python -m pip install -e ".[dev]"
pyinstaller --noconfirm --clean packaging/s4mod-steward.spec
```

仓库包含 Windows/macOS 自动打包流程。本地开发包没有签名，详见
[打包说明](./packaging/README.md)。

## 开发检查

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

测试只能使用虚构字节。仓库不能包含真实 Mod、付费内容、用户清单、凭证、私人电脑路径或私有参考材料。

作者：[Iris](https://irisli.dev/)。项目案例见 Iris 的 3D 作品集 [RIRRI'S](https://world.irisli.dev/#/work/sims4-steward)。

项目使用 [MIT License](./LICENSE)。这是非官方玩家工具，与 Electronic Arts、Maxis 或 The Sims 无关联。
