# Bee's Ultimate Grammar Dictionary — 中文版

这是一个以中文为主的日语语法统一词典，适用于 [Yomitan](https://github.com/yomidevs/yomitan)。它将 **12 个来源**合并为一个可安装的词典，并保留统一检索和逐来源署名。

本项目是 [bee-san/bees-ultimate-grammar-dictionary](https://github.com/bee-san/bees-ultimate-grammar-dictionary) 的自动更新分支。

## 语言处理规则

- 纯英文来源（DoJG、Bunpro、IMABI、Yokubi）保留英文原文，并增加单独标注的简体中文翻译。
- 含日语或日英双语内容的来源保留日语部分，删除英文解释和例句译文。
- 已锁定的来源字节不会被修改。语言处理在合并前对规范化记录执行，翻译结果按来源文本缓存。

### 译文质量门（`bugd.translation_quality`）

译文必须原样保留它所解释的日语、链接和标记——一段丢掉了语法点本身的讲解等于什么都没讲。
不满足这一条的译文会被**丢弃而不是渲染**，卡片退回显示该来源自己的英文原文。

判定为不可用的四种情况：占位符残渣、丢失原文中受保护的片段、解码重复循环、译文明显截断。
这四条同时作用于三个位置——Argos 离线翻译、OpenAI 翻译、以及 `apply_translation_chunks.py`
的入库环节——所以一次翻译跑崩不会再把垃圾写进缓存、更不会进入发布包。

日语片段不再用 `ZXQJPN00001Q` 之类的哨兵占位再还原：子词 NMT 不会把自造 token 原样解出来，
它会改写、切碎甚至音译它。现在这些片段根本不进模型，只翻译它们之间的英文段落再按原位拼回。

更新流程会重新构建词典、验证 Yomitan ZIP，并发布版本。翻译在本地完成后再上传发布；不依赖 GitHub Actions 在线调用翻译服务。

## 安装

1. 从 [Releases](https://github.com/W1ght/bees-ultimate-grammar-dictionary/releases) 下载最新的 `.zip`。
2. 在 Yomitan 设置中进入“词典 → 导入”。
3. 选择下载的 ZIP 文件。

## 包含内容

每个语法点都会显示一个紧凑卡片；点击后可展开各来源详情、额外例句和来源信息。

### 来源

| 来源 | 名称 | 语言 | 说明 |
|--------|------|----------|-------------|
| DoJG | 日本語文法辞典(全集) | EN | 《日语语法辞典》（基础/中级/高级） |
| HJGP | 日本語文型辞典 | JA | 《日语句型辞典》——日语单语版 |
| HJGP EN | 日本語文型辞典 英語版 | EN | 《日语句型辞典》——英文版 |
| NINJAL | 日本語文型データベース | JA | 日本国立国语研究所日语句型数据库 |
| 日本語NET | JLPT文法解説まとめ | JA | 来自 nihongokyoshi-net.com 的 JLPT 语法解释 |
| 絵でわかる | 絵でわかる日本語 | JA | 通过插图讲解日语语法 |
| Donna Toki | どんなときどう使う 日本語表現文型辞典 | EN/JA | “何时以及如何使用”表达句型辞典 |
| 日本語教師 | 毎日のんびり日本語教師 | JA/ZH | 面向日语教师的语法解释 |
| Bunpro | Bunpro Grammar Reference | EN | 基于 SRS 的语法参考资料 |
| 文法 | 文法 | JA | 个人语法 Anki 卡组 |
| IMABI | IMABI | EN | 全面的日语语法课程（现代语和古典语） |
| Yokubi | Yokubi | EN | Common Grammar Guide（yoku.bi） |

### 与分别安装各词典相比有什么不同？

- **统一检索**：一个词典、每个语法点一张卡片，不会弹出 12 个独立窗口。
- **合并词条**：多个来源描述同一语法点时，合并到一张卡片中，并分别标明来源。
- **去重对齐**：keymap 阶段会对齐不同来源的词条，减少重复显示。
- **渐进式展开**：默认显示紧凑卡片，需要时再展开任意来源的详细内容。

## 从源码构建

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/apply_translation_chunks.py
PYTHONPATH=src python scripts/localize_chinese.py --offline
PYTHONPATH=src python -m bugd.cli all
```

如果 `data/extracted/` 里还残留着旧版本写入的坏译文，先跑一次隔离：

```
PYTHONPATH=src python scripts/quarantine_bad_translations.py
```

它只删除未通过质量门的译文值，不碰来源英文，可重复执行。

词典更新在本地完成后再推送到 GitHub。`.github/workflows/update-dictionary.yml` 仅提供手动发布入口，不会自动同步上游或在线翻译。

流水线阶段：

1. **extract** — 将每个来源的锁定数据读取为规范化的 `GrammarPoint` 记录。
2. **keymap** — 对齐不同来源的词条，判断哪些记录属于同一个语法点。
3. **merge** — 将已对齐的记录合并为统一数据集。
4. **build** — 生成 Yomitan 词典 ZIP。
5. **validate** — 根据 Yomitan JSON Schema 进行验证。

## 添加新来源

1. 将来源数据放入 `data/sources/<name>/`，并提供 `SOURCE.lock.json`。
2. 在 `src/bugd/sources/<name>.py` 中编写提取器，可参考现有提取器。
3. 使用 `@register_extractor` 注册提取器。
4. 将来源加入 `keymap.py` 的 `SOURCE_PRECEDENCE` 和 `banks.py` 的 `_SOURCE_EXPLANATION_LANG`。
5. 执行 `make all`。

## 许可证

词典内容继续遵循各来源原有的许可协议；构建流水线代码采用 MIT 许可证。
