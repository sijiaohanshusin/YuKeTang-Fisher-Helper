# 雨课堂助手 Windows Desktop

持续发现已加入班级的课堂，按独立开关自动签到、调用视觉模型作答并提交有效答案。新安装默认观察模式，不产生考勤或答题记录。

## 一键安装

前往 [Releases](https://github.com/sijiaohanshusin/YuKeTang-Fisher-Helper/releases/latest) 下载 **YuketangHelper-Setup-v2.1.0-Windows-x64.exe**，双击安装。无需 Python、Node.js 或管理员权限。安装后从桌面或开始菜单打开，跟随五步配置向导完成：

1. 微信扫码登录，普通主站选择 `www.yuketang.cn`。
2. 配置支持图片输入的模型，并验证电路图示例。
3. 选择已加入的班级，可搜索、全选或只选择正在上课的班级。
4. 选择观察、AI 试答或自动运行，独立控制签到和答案提交。
5. 核对后保存，程序持续运行；无课等待，下课后继续发现下一节。

也可下载 Portable 压缩包，解压后双击 `YuketangHelper.exe`。发布页另附 SHA256SUMS 与可选的 `install-latest.ps1` 部署脚本。

## 运行方式

| 模式 | 进入并签到 | AI 作答 | 答案提交 |
| --- | --- | --- | --- |
| 观察 | 关闭 | 不建立课堂连接 | 关闭 |
| AI 试答 | 独立开关 | 取得课堂令牌后试答 | 强制关闭 |
| 自动运行 | 独立开关 | 取得课堂令牌后作答 | 独立开关 |

当前已知课堂连接流程需要先签到取得令牌。微信登录码与课堂签到是不同流程，不需要逐节提供课堂二维码图片。

AI 未配置、失败、格式无效或超时会跳过，不会随机蒙答或提交空白。同一课次同一题持久防重，响应未知时不盲目重发。界面分别显示题面就绪、AI 格式有效、请求已发送、服务器接受与服务器拒绝。

## 题型

| 题型 | 本地模拟提交 | 真实课堂验证 |
| --- | --- | --- |
| 单选 | 通过 | 已取得题图并产生 AI 试答；真实提交待验证 |
| 多选 | 通过 | 待验证 |
| 投票 | 通过，遵守可选数量 | 待验证 |
| 简答 | 通过 | 待验证 |
| 填空 | 明确跳过 | 不宣称支持 |

“提交自检”可一键运行 16 个场景，使用模拟 AI 和本机 HTTP 服务。模拟服务接受不等于真实雨课堂接受，答案格式有效也不等于答案正确。

## 数据与停止

安装版配置和日志位于 `%LOCALAPPDATA%\YuketangHelper`。免安装版使用解压目录下的 `store` 与 `logs`。发布包不含任何个人会话、密钥、课程或课堂记录。卸载保留个人数据；停止入口位于开始菜单，免安装版可用 `stop.cmd`。

关闭浏览器不结束后台进程。系统休眠、关机或断网会中断监听，恢复后程序尝试重连。健康状态应结合发现循环最近成功时间和课堂 Pong，不能只看进程存活。

## 从源码运行

Windows 已有 Python 3.11+ 与 Node.js 时，双击 `init-local.bat` 初始化，再运行 `start-local.bat`。访问 [本机运行台](http://127.0.0.1:8500/experiment)。`stop-local.bat` 停止，`logs-local.bat` 查看日志。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/build_release.py --compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

构建前安装 `backend/requirements-local.lock.txt` 与 `backend/requirements-build.txt`。构建脚本会验证前端、行为测试、模拟 HTTP 提交、冻结程序启动／停止及安装／卸载，再生成白名单分发包。GitHub Actions 在干净 Windows runner 上重复构建验证。

源码本地入口继续使用项目 `.venv`；打包后的安装版不依赖目标机器上的 Python 或 Node.js。当前发布仅验证 Windows x64，未将其描述为 Linux/macOS 验证结果。

详细说明：[分发使用说明](分发使用说明.md)、[本机实验使用说明](本地使用说明.md)、[历史验证记录](验证记录.md)、[本次发布说明](RELEASE_NOTES.md)。

## 社区

感谢 [LINUX DO](https://linux.do/) 社区提供软件分享与开发交流的平台。

## 来源

本分支基于 [Nijika-jia/YuKeTang-Fisher-Helper](https://github.com/Nijika-jia/YuKeTang-Fisher-Helper)，其上游为 [dvdsanyi/Yuketang-Helper-Web](https://github.com/dvdsanyi/Yuketang-Helper-Web)，并注明参考 [RainClassroomAssitant](https://github.com/TrickyDeath/RainClassroomAssitant) 与 [THU-Yuketang-Helper](https://github.com/zhangchi2004/THU-Yuketang-Helper)。原始快照提交为 cc46b316fe3b37499f463e28e5a8f634df1416e8。

上游 README 声明 MIT，本次原始快照未附 LICENSE 文件；完整来源与组件许可说明见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
