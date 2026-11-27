# AIM-Lab DSH 品牌插件

`@aim-lab/dsh-brand` 为 DeepSeek Harness（DSH）提供自定义界面：侧边栏显示项目标识与名称，首页不再显示大图标，首页标语替换为「开始本次结构设计任务」。

## 安装

要求：DeepSeek Harness Desktop 或 Web（0.2.x）、Node.js 24。

本插件是零依赖、无构建步骤的 DSH bundle，可直接以本地目录安装；也可以在插件目录中打包后再安装：

```sh
npm run pack
dsh plugin --profile desktop add ./artifacts/aim-lab-dsh-brand-0.1.0.tgz
dsh plugin --profile web add ./artifacts/aim-lab-dsh-brand-0.1.0.tgz
```

把命令中的压缩包路径换成插件目录的绝对路径，效果相同。安装后在「设置 → 插件」确认 `@aim-lab/dsh-brand` 已启用，然后重启 DSH 或刷新页面。

## 使用

启用后界面立即按以下方式呈现：

- 侧边栏左上角显示本插件的标识和名称「火箭总体结构辅助设计智能体」；
- 首页（空会话）不再显示大图标；
- 首页标语显示为「开始本次结构设计任务」。

首页的「预览版」徽章由 DSH 自身提供，本插件不修改。

## 配置

本插件没有运行时配置项，界面文本与图标随包提供。需要调整时直接修改包内文件：

- 名称文案：`client.js` 中 `BrandName` 组件的文本；
- 首页标语：`client.js` 中的 `SLOGAN` 常量；
- 标识图片：`client.js` 中的 `EMBLEM` 内联 `data:image/png;base64` 图片，需与 `icon.png` 保持一致（`npm test` 会校验两者一致）；
- 插件在「设置 → 插件」中的标题和描述：`locale/zh.json`、`locale/en.json`。

修改后执行 `npm run check`、`npm test`，重新安装或刷新页面生效。

## 卸载

在「设置 → 插件」停用或移除 `@aim-lab/dsh-brand`，重新启用内置的 `@deepseek-ai/dsh-client-ui-brand-official`，然后重启 DSH 或刷新页面以恢复默认界面。
