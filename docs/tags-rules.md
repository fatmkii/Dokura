# 同人志文件名命名与解析规则

> 用途：为 Dokura 的文件扫描、元数据提取、搜索、去重及重命名功能提供设计依据。  
> 文档性质：社区事实规范（de facto convention），并非官方强制标准。  
> 更新日期：2026-07-11

## 1. 结论

同人志压缩包常见文件名大致遵循以下结构：

```text
(活动/场次) [社团名 (作者名)] 作品标题 (原作/系列) [语言/翻译状态] [版本] [汉化组/发布组] [其他标签].扩展名
```

完整示例：

```text
(C106) [毛玉丸] シロコたちは先生の○○○が欲しい (ブルーアーカイブ) [中国翻訳] [欶澜汉化组].zip
```

但所有字段几乎都是可选的。最稳定的特征是：

1. 文件主体通常由若干括号块和一段自由文本标题组成。
2. 开头的半角圆括号通常表示活动或展会场次。
3. 标题前的第一个方括号通常表示社团、作者或发布者。
4. 标题后的圆括号通常表示原作、系列或 fandom。
5. 末尾的方括号通常表示语言、翻译、版本、汉化组或其他附加标签。

因此，Dokura 不应把格式视为严格语法，也不应依靠一条正则表达式完成全部解析。推荐使用“分词 → 位置判断 → 标签分类 → 置信度评分”的多阶段解析方式。

---

## 2. 常见字段

| 字段 | 常见写法 | 示例 | 是否必有 |
|---|---|---|---|
| 活动/场次 | `(C106)`、`(COMIC1☆25)`、`(例大祭21)` | `(C106)` | 否 |
| 社团/作者块 | `[社团名 (作者名)]`、`[作者名]` | `[きのこむ神 (きのこむし)]` | 常见，但非必有 |
| 标题 | 无固定包围符号的自由文本 | `永き夜の現に堕ちて` | 通常有 |
| 原作/系列 | `(作品名)` | `(ブルーアーカイブ)` | 否 |
| 语言/翻译 | `[中国翻訳]`、`[English]`、`[翻訳済]` | `[中国翻訳]` | 否 |
| 版本 | `[DL版]`、`[Digital]`、`[無修正]` | `[DL版]` | 否 |
| 汉化/发布组 | `[欶澜汉化组]`、`[某某掃圖組]` | `[欶澜汉化组]` | 否 |
| 其他标签 | `[カラー化]`、`[ページ欠落]` 等 | 视资源而定 | 否 |
| 扩展名 | `.zip`、`.cbz`、`.rar`、`.7z`、`.pdf` | `.zip` | 是 |

---

## 3. 推荐的规范化格式

Dokura 在需要生成或重命名文件时，建议使用：

```text
{event?} {creator_block?} {title} {parody?} {language_tags*} {edition_tags*} {group_tags*}{extension}
```

对应的人类可读格式：

```text
(活动) [社团 (作者)] 标题 (原作) [语言] [版本] [汉化组].zip
```

### 3.1 推荐顺序

```text
1. 活动
2. 社团/作者
3. 标题
4. 原作/系列
5. 语言及翻译状态
6. 版本信息
7. 汉化组/扫描组/发布组
8. 其他附加标签
9. 扩展名
```

### 3.2 空格规则

- 各顶级字段之间使用一个半角空格。
- 文件扩展名前不加空格。
- 不应修改标题、社团名或作者名内部原有空格。
- 解析时应兼容多个空格、全角空格和无空格情况。

### 3.3 括号规则

建议新生成的文件名统一采用：

- 活动、原作：半角圆括号 `()`
- 社团、作者、标签：半角方括号 `[]`
- 社团块中的作者：半角圆括号 `()`

解析时还应兼容：

```text
（） ［］ 【】 〔〕
```

但规范化输出时不建议继续使用这些异体括号。

---

## 4. 各字段详细说明

## 4.1 活动或场次 `event`

典型位置：文件名最前方。

```text
(C106)
(C105)
(COMITIA149)
(例大祭21)
(サンクリ2025 Summer)
```

### 判断建议

位于文件名开头的圆括号块，且内容符合以下任一特征时，可判定为活动：

- `C` 加数字，例如 `C106`；
- 包含 `COMITIA`、`COMIC1`、`例大祭`、`サンクリ` 等已知活动词；
- 包含年份、届数、日期或场次信息；
- 命中可维护的活动别名字典。

不要简单地把开头所有圆括号都视为活动。未知内容应保存为 `unknown_prefix_token`，等待后续规则或外部元数据确认。

---

## 4.2 社团与作者 `circle` / `artists`

典型写法：

```text
[きのこむ神 (きのこむし)]
[毛玉丸]
[ヴィヴィ堂 (クマ作民三)]
[Breakthrough]
```

常见语义：

```text
[社团名 (作者名)]
[作者名]
[社团名]
[作者1, 作者2]
```

### 解析原则

方括号内部含有末尾圆括号时，可优先解释为：

```text
circle = 圆括号之前的文本
artists = 圆括号内部的文本
```

例如：

```text
[きのこむ神 (きのこむし)]
```

解析为：

```yaml
circle: きのこむ神
artists:
  - きのこむし
```

但该规则不能绝对化，原因包括：

- 有些作者名本身含括号；
- 有些方括号只有社团名，没有作者；
- 有些方括号直接列出多个作者；
- 有些投稿者把出版社、下载站或发布组放在标题前。

因此应保留原始值：

```yaml
creator_raw: "きのこむ神 (きのこむし)"
```

并允许人工修正。

### 多作者分隔符

解析时可尝试识别：

```text
,  ，  、  &  ＆  x  ×  /  ・
```

但默认不要对 `・` 强制切分，因为它也常是日文名字的一部分。

---

## 4.3 标题 `title`

标题通常是去除前缀活动块、创作者块及末尾元数据块后剩余的自由文本。

```text
永き夜の現に堕ちて
シロコたちは先生の○○○が欲しい
ユウカとお泊まり 汗だくハメハメパーティ
門主の一夢
```

### 注意事项

标题可能自身包含：

- 圆括号；
- 方括号；
- 卷号，例如 `Vol.2`、`前編`、`下巻`；
- 系列名；
- 特殊符号；
- 日文全角标点；
- 中英文混排。

因此标题不适合仅通过“第一个 `(` 到最后一个 `)`”之类的简单规则截取。

### 标题清理

允许进行的规范化：

- 去除首尾空白；
- 将连续的顶级空白折叠为一个半角空格；
- Unicode 规范化建议采用 NFC；
- 去除扩展名。

不建议自动进行：

- 日文汉字转简体；
- 大小写统一；
- 全角字符全部转半角；
- 删除标点；
- 翻译标题；
- 删除疑似重复词。

这些操作可能破坏原始标题及后续匹配能力。

---

## 4.4 原作或系列 `parodies` / `series`

典型位置：标题之后、末尾标签之前。

```text
(ブルーアーカイブ)
(東方Project)
(原神)
(オリジナル)
```

在同人志数据库中，该字段常被称为：

- parody
- series
- source
- fandom
- original work

Dokura 推荐内部使用 `parodies` 或 `source_works`，并允许数组：

```yaml
source_works:
  - ブルーアーカイブ
```

### 判断建议

一个圆括号块同时满足以下条件时，可较高置信度识别为原作：

- 出现在标题之后；
- 后面主要只剩方括号标签；
- 内容命中作品词典；
- 内容为 `オリジナル`、`Original` 等原创标记。

标题中的普通圆括号不能直接当作原作字段。

---

## 4.5 语言与翻译状态 `languages` / `translation_status`

常见标签：

```text
[中国翻訳]
[中国語]
[Chinese]
[English]
[英訳]
[韓国翻訳]
[Russian]
[翻訳済]
[機械翻訳]
```

`[中国翻訳]` 在该命名生态中通常表示“已翻译为中文”，并不表示作品来自中国。

建议内部拆分：

```yaml
languages:
  - zh
translated: true
translation_method: unknown
language_raw:
  - 中国翻訳
```

### 规范化映射示例

| 原始标签 | 建议语言码 | translated |
|---|---:|---:|
| 中国翻訳 | `zh` | true |
| 中国語 | `zh` | 不确定 |
| Chinese | `zh` | 不确定 |
| English / 英訳 | `en` | 视标签判断 |
| 日本語 | `ja` | 不确定 |
| 機械翻訳 | 未知或结合其他标签 | true |

语言和翻译状态应分开保存，因为“语言为中文”并不必然意味着“由其他语言翻译而来”。

---

## 4.6 版本与介质 `edition_tags`

常见标签：

```text
[DL版]
[Digital]
[デジタル版]
[電子版]
[冊子版]
[Scan]
[無修正]
[修正版]
[カラー化]
```

`[DL版]` 通常表示下载版、数字发行版，与纸质本扫描版相区别。

建议规范化：

```yaml
edition:
  medium: digital
  raw_tags:
    - DL版
```

不要仅凭文件是 ZIP 就推断为数字发行版；纸质扫描件同样经常被打包为 ZIP。

---

## 4.7 汉化组、扫描组与发布组 `groups`

常见位置：文件名末尾的方括号块。

```text
[欶澜汉化组]
[某某漢化]
[某某掃圖組]
[某某翻译组]
```

建议内部模型：

```yaml
groups:
  - name: 欶澜汉化组
    role: translation
```

角色可取：

```text
translation
scan
editing
release
unknown
```

仅凭名称无法稳定判断时，角色使用 `unknown`，保留原始标签。

---

## 5. 用户提供案例的解析结果

## 5.1 案例一

```text
(C106) [きのこむ神 (きのこむし)] 永き夜の現に堕ちて (ブルーアーカイブ) [中国翻訳].zip
```

```yaml
event: C106
circle: きのこむ神
artists:
  - きのこむし
title: 永き夜の現に堕ちて
source_works:
  - ブルーアーカイブ
languages:
  - zh
translated: true
groups: []
edition_tags: []
extension: zip
```

## 5.2 案例二

```text
(C106) [毛玉丸] シロコたちは先生の○○○が欲しい (ブルーアーカイブ) [中国翻訳] [欶澜汉化组].zip
```

```yaml
event: C106
creator_raw: 毛玉丸
circle: null
artists:
  - 毛玉丸
title: シロコたちは先生の○○○が欲しい
source_works:
  - ブルーアーカイブ
languages:
  - zh
translated: true
groups:
  - name: 欶澜汉化组
    role: translation
extension: zip
```

说明：仅凭文件名无法确定“毛玉丸”是社团还是个人作者。上述结果只是较合理的默认推断，因此必须保留 `creator_raw`，并允许后续数据库覆盖。

## 5.3 案例三

```text
[ヴィヴィ堂 (クマ作民三)] ユウカとお泊まり 汗だくハメハメパーティ (ブルーアーカイブ) [中国翻訳] [DL版] [欶澜汉化组].zip
```

```yaml
event: null
circle: ヴィヴィ堂
artists:
  - クマ作民三
title: ユウカとお泊まり 汗だくハメハメパーティ
source_works:
  - ブルーアーカイブ
languages:
  - zh
translated: true
edition:
  medium: digital
groups:
  - name: 欶澜汉化组
    role: translation
extension: zip
```

## 5.4 案例四

```text
[Breakthrough] 門主の一夢 (ブルーアーカイブ) [中国翻訳] [欶澜汉化组].zip
```

```yaml
event: null
creator_raw: Breakthrough
circle: Breakthrough
artists: []
title: 門主の一夢
source_works:
  - ブルーアーカイブ
languages:
  - zh
translated: true
groups:
  - name: 欶澜汉化组
    role: translation
extension: zip
```

说明：`Breakthrough` 也可能是作者名或发布者，仅靠文件名无法绝对确定。

---

## 6. 推荐的数据结构

```json
{
  "original_filename": "(C106) [きのこむ神 (きのこむし)] 永き夜の現に堕ちて (ブルーアーカイブ) [中国翻訳].zip",
  "basename": "(C106) [きのこむ神 (きのこむし)] 永き夜の現に堕ちて (ブルーアーカイブ) [中国翻訳]",
  "extension": "zip",
  "event": "C106",
  "creator_raw": "きのこむ神 (きのこむし)",
  "circle": "きのこむ神",
  "artists": ["きのこむし"],
  "title": "永き夜の現に堕ちて",
  "source_works": ["ブルーアーカイブ"],
  "languages": ["zh"],
  "translated": true,
  "edition": null,
  "groups": [],
  "unclassified_tags": [],
  "parse_confidence": 0.94,
  "parse_warnings": []
}
```

### 必须保留的字段

无论解析成功与否，都建议保留：

```text
original_filename
basename
extension
creator_raw
unclassified_tags
parse_confidence
parse_warnings
```

不能因为字段已经被规范化就丢弃原始文本。

---

## 7. 推荐解析流程

## 7.1 预处理

1. 分离扩展名，支持 `.zip`、`.cbz`、`.rar`、`.7z`、`.pdf` 等。
2. 执行 Unicode NFC 规范化。
3. 去除首尾空白。
4. 记录原始文件名，不覆盖原值。
5. 建立括号层级，识别顶级括号块。
6. 兼容半角和全角括号，但不要修改括号内文本。

## 7.2 从左侧提取前缀

1. 检查第一个顶级圆括号块是否像活动名。
2. 检查紧随其后的第一个顶级方括号块是否像创作者块。
3. 不能识别的前缀块保留到未知字段，不要直接丢弃。

## 7.3 从右侧反向提取标签

从文件名末尾向前连续读取顶级方括号块：

```text
[中国翻訳] [DL版] [欶澜汉化组]
```

依次通过标签词典分类为：

```text
language
translation_status
edition
release_group
other
```

反向提取比从左到右扫描更稳定，因为附加标签通常集中在末尾。

## 7.4 识别原作块

移除末尾方括号标签后，检查最后一个顶级圆括号块：

- 若命中作品词典或原创标记，识别为 `source_works`；
- 若没有命中，只作为候选，降低置信度；
- 若标题中有多个圆括号，只优先考虑最靠右且位于标签之前的块。

## 7.5 得到标题

前缀和后缀字段移除后，剩余文本作为标题。若为空，应判定解析失败并回退：

```yaml
title: 原始 basename
parse_confidence: 0
parse_warnings:
  - EMPTY_TITLE_AFTER_PARSE
```

---

## 8. 不建议只使用单条正则

可用一个宽松正则完成初步切分：

```regex
^(?:(?<event>\([^\r\n]*?\))\s*)?(?:(?<creator>\[[^\r\n]*?\])\s*)?(?<rest>.+)$
```

但它只能识别候选前缀，不能可靠判断：

- 圆括号属于活动、作者还是标题；
- 方括号属于作者、语言还是标题本身；
- `()` 是否嵌套在 `[]` 内；
- 标题是否含括号；
- 多作者、多原作和异常括号。

正式实现应使用状态机或字符扫描器构建顶级 token：

```text
TEXT
ROUND_BLOCK
SQUARE_BLOCK
```

每个 token 至少记录：

```yaml
type: SQUARE_BLOCK
raw: "[中国翻訳]"
content: "中国翻訳"
start: 48
end: 54
depth: 0
```

---

## 9. 标签分类词典

初始版本可以维护以下可扩展词典。

### 9.1 语言词典

```yaml
中国翻訳: { language: zh, translated: true }
中国語: { language: zh }
Chinese: { language: zh }
English: { language: en }
英訳: { language: en, translated: true }
日本語: { language: ja }
Japanese: { language: ja }
韓国語: { language: ko }
Korean: { language: ko }
```

### 9.2 版本词典

```yaml
DL版: { medium: digital }
Digital: { medium: digital }
デジタル版: { medium: digital }
電子版: { medium: digital }
冊子版: { medium: print }
Scan: { medium: scan }
```

### 9.3 组名启发式

包含下列后缀时，可作为组名候选：

```text
汉化组
漢化組
翻译组
翻譯組
掃圖組
扫图组
制作组
製作組
```

这只是启发式规则，不应覆盖明确的词典结果。

---

## 10. 置信度与冲突处理

建议每个字段分别记录置信度，而不仅是整个文件一个分数：

```json
{
  "confidence": {
    "event": 0.99,
    "creator": 0.78,
    "title": 0.96,
    "source_works": 0.91,
    "languages": 0.99,
    "groups": 0.87
  }
}
```

示例评分原则：

| 条件 | 分数影响 |
|---|---:|
| `(C数字)` 位于开头 | event 高置信度 |
| 标题前第一个方括号 | creator 中高置信度 |
| 最后圆括号命中作品词典 | source 高置信度 |
| 标签精确命中语言词典 | language 高置信度 |
| 仅根据“汉化组”后缀识别 | group 中等置信度 |
| 括号不匹配 | 整体显著降分 |
| 删除字段后标题为空 | 解析失败 |

当外部元数据与文件名冲突时，建议优先级为：

```text
人工确认 > 内嵌 ComicInfo/JSON > 可信数据库 > 文件名解析 > 文件夹名推断
```

---

## 11. 文件系统兼容性

Dokura 可能运行在 Linux Docker 中，但文件实际位于 Windows、SMB 或 NAS 上，因此生成文件名时应按最严格环境处理。

### 禁止或替换字符

Windows 文件名禁止：

```text
< > : " / \ | ? *
```

推荐仅在“实际重命名”阶段替换，数据库中的原始标题不要替换。

建议映射：

```text
:  → ：
/  → ／
\  → ＼
?  → ？
*  → ＊
"  → ＂
<  → ＜
>  → ＞
|  → ｜
```

### 其他限制

- 去除文件名末尾的空格和句点；
- 避免 Windows 保留名，如 `CON`、`PRN`、`AUX`、`NUL`；
- 设置可配置的最大文件名长度；
- 重命名前检查同名冲突；
- 不应以文件名作为数据库唯一主键。

---

## 12. 去重建议

文件名只能作为弱去重信号。建议组合：

```text
文件内容哈希
图片感知哈希
页数
文件大小
规范化标题
作者/社团
原作
来源站点 ID
```

规范化标题可用于候选召回，但不要直接据此自动删除文件。

推荐建立：

```yaml
identity:
  content_sha256: "..."
  cover_phash: "..."
  source_ids:
    ehentai: null
    nhentai: null
```

---

## 13. 异常文件名及回退策略

需要兼容：

```text
无任何括号的标题.zip
[作者] 标题.zip
标题 (原作).zip
(C106) 标题.zip
[汉化组] [作者] 标题.zip
标题 [中国翻訳] v2.zip
网站名@标题.zip
123456 标题.zip
```

回退原则：

1. 永远能够导入文件；
2. 无法分类的块保存为 `unclassified_tags`；
3. 无法解析时将完整 basename 作为显示标题；
4. 不因解析失败拒绝生成缩略图；
5. 后续可通过外部数据库或人工操作重新解析；
6. 解析器升级后允许批量重跑，但不得覆盖人工修正字段。

---

## 14. 建议的数据库字段来源策略

每个元数据字段建议记录来源：

```json
{
  "title": {
    "value": "永き夜の現に堕ちて",
    "source": "filename_parser",
    "confidence": 0.96,
    "locked": false
  }
}
```

当用户手动编辑后：

```json
{
  "title": {
    "value": "永き夜の現に堕ちて",
    "source": "user",
    "confidence": 1.0,
    "locked": true
  }
}
```

重新扫描文件时，不覆盖 `locked: true` 的字段。

---

## 15. 推荐的首版实现范围

Dokura 第一版解析器建议只稳定支持：

```text
(event?) [creator] title (source?) [trailing tags...]
```

首版实现：

- 活动识别；
- 创作者原始块提取；
- 简单的社团/作者拆分；
- 标题提取；
- 原作候选提取；
- 中文、英文、日文语言标签；
- `DL版` / `Digital`；
- 汉化组后缀识别；
- 未分类标签保留；
- 置信度和警告；
- 单元测试。

首版不建议追求：

- 从任意复杂名字中 100% 区分社团和作者；
- 自动翻译或罗马音转换；
- 通过文件名判断成人分类；
- 仅凭标题完成自动删除；
- 将所有括号内容强行分类。

---

## 16. 单元测试样例

至少覆盖用户提供的四个案例，以及以下边界情况：

```text
(C106) [Circle (Artist)] Title (Series) [中国翻訳] [DL版] [某某汉化组].zip
[Artist] Title.zip
Title (Original).cbz
(C105) Title [English].rar
[Artist1, Artist2] Title (Series A, Series B) [Digital].7z
[Circle (Artist)] Title (Part 2) (Series).zip
Title [Unknown Tag].zip
(C106 [Broken Bracket] Title.zip
```

每个测试同时验证：

- 字段值；
- 未分类标签；
- 警告代码；
- 置信度范围；
- 原始文件名未被改写。

---

## 17. 参考资料

调研表明，该格式主要是资源社区和管理软件所采用的事实约定，而非正式标准：

1. LANraragi 项目案例给出的典型文件名：  
   `(C96) [Some Group (Artist)] Amazing Book (Berserk) [English]`  
   https://github.com/Difegue/LANraragi/issues/232

2. LANraragi 提供 Filename Parsing 插件，可从文件名填充标题及元数据；相关讨论也说明文件名匹配并非绝对可靠：  
   https://github.com/Difegue/LANraragi/discussions/482

3. LANraragi 对多作者文件名解析的改进讨论，表明现实数据中存在多个作者及复杂创作者块：  
   https://github.com/Difegue/LANraragi/issues/1084

4. LANraragi 的 nHentai 插件还支持 `{Id} Title` 形式，说明不同下载来源可能使用完全不同的前缀规范：  
   https://github.com/Difegue/LANraragi/discussions/938

5. 同人志的创作主体通常称为 circle，且 circle 既可能是多人团体，也可能只有一名作者：  
   https://fanlore.org/wiki/Doujinshi_Circle

6. 同人志是一类自主出版作品，既可能是二次创作，也可能是原创作品，并通过展会或数字平台发行：  
   https://en.wikipedia.org/wiki/Doujinshi

---

## 18. 最终建议

Dokura 应把文件名看成“可利用但不可信的元数据载体”：

```text
读取它，但不依赖它；
解析它，但保留原文；
给出推断，但允许修正；
支持重跑，但保护人工数据。
```

推荐的内部解析目标不是让所有文件名都严格符合一种格式，而是尽可能从杂乱历史文件中提取候选元数据，并让后续数据库匹配及人工管理能够继续完善结果。
