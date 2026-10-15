# 长期分类方案

目标：Clash / Mihomo 与 Surge 从同一数据构建规则，分类边界可解释、上游变化可审计。只统一规则内容与更新流程，不要求两端使用相同策略、Wi-Fi 行为或兜底。实际接入以私有客户端配置为准。

## 分类边界

| 分类 | 来源 / 范围 | 关系与使用建议 |
| --- | --- | --- |
| Claude | MetaCubeX `anthropic` 加 `custom/overrides.json` 中两条后缀、两条关键词 | 合并为 classical `claude_domain`；先于 AI 和 Wi-Fi 直连匹配；完整宽匹配范围不等于 AI 子集 |
| AI | MetaCubeX `category-ai-!cn` | 保留完整 AI 总集合，包含 Claude 作为兜底；不能整段并入媒体 |
| Netflix | 现有 MetaCubeX 域名和 IP 集合 | 需要独立策略时先于 GlobalMedia |
| YouTube | 新增 MetaCubeX `youtube` | 可单独路由，也可直接指向现有 GlobalMedia 策略；不强制新增客户端策略组 |
| GlobalMedia | 下列 20 个影音服务的明确清单 | 按服务边界维护，替代宽泛的 `category-entertainment`；不含 AI、游戏和小说大集合 |
| Google / Microsoft / Apple | 保留各自 MetaCubeX 分类 | 公司分类是较宽的兜底，不从中强删 AI、影音等合理子集 |
| OneDrive / GitHub / PayPal / 银行 / Telegram | 保留各自专用分类 | 小类先于公司类、通用 Proxy 类 |
| APNS | 原 QuixoticHeart 13 条 classical 规则 | 独立于普通 Apple 服务，放在 Apple 前；保留 YAML / Surge 格式 |
| CN / Private / 通用 Proxy | 现有域名和 IP 来源 | 作为基础/通用分类，不在这次重构中更改用户的直连和兜底逻辑 |
| Fake-IP 排除 | 原 wwqgtxx 来源 | 仅用于 Mihomo DNS，不当作业务路由集合 |

不追求所有集合完全互斥：YouTube 属于 Google、Apple Music 属于 Apple，是正常的包含关系。拆成“小类覆盖大类”比从公司集合不断剔除子集更稳健。否则，某个客户端未启用小类时反而可能漏掉原本应有的公司分类。

## GlobalMedia 的明确服务清单

所有组件使用同一个 MetaCubeX `meta` 分支快照，路径和最低条数在 [sources.json](../sources.json) 中维护。

| 服务 | 上游名称 | 导入范围 |
| --- | --- | --- |
| YouTube | `youtube` | 全部 |
| Netflix | `netflix` | 全部 |
| Disney+ | `disney` | 仅 `select` 列出的 13 条服务、账号、资源/CDN、订阅及相关隐私/条款域名 |
| HBO / Max | `hbo` | 全部 |
| Prime Video | `primevideo` | 全部 |
| Apple TV+ | `apple-tvplus` | 全部 |
| Spotify | `spotify` | 全部 |
| Twitch | `twitch` | 全部 |
| Hulu | `hulu` | 全部 |
| ABEMA | `abema` | 全部 |
| DAZN | `dazn` | 全部 |
| Discovery+ | `discoveryplus` | 全部 |
| Vimeo | `vimeo` | 全部 |
| Dailymotion | `dailymotion` | 全部 |
| Pluto TV | `plutotv` | 全部 |
| Deezer | `deezer` | 全部 |
| TIDAL | `tidal` | 全部 |
| SoundCloud | `soundcloud` | 全部 |
| Apple Music | `apple-music` | 全部 |
| Apple Podcasts | `apple-podcasts` | 全部 |

“影音服务”指服务及其上游列出的相关网站、账号、静态资源、CDN 等，不代表只有视频音频传输请求。此清单不是全球所有流媒体的全集；未列入的服务（例如 TikTok、其他地区平台）不会自动加入 GlobalMedia，按客户端后续规则处理。需要新增时审查服务级名单并加回归样例，不用“娱乐”大集合补齐。

### 为什么 Disney+ 要单独筛选

上游 [`disney`](https://github.com/v2fly/domain-list-community/blob/master/data/disney) 同时包含乐园、商店、漫威及游戏等，直接导入不符合本次范围。本仓库选择已核实的服务相关条目，不导入这些明显非影音的品牌类别。

筛选名单也不是经过完整抓包证明的最小充分集合：账号和静态资源中可能存在与其他 Disney 业务共用的域名。不能保证每个 Disney+ 登录、播放和付款场景都仅使用这些域名；若以后实际连接日志发现缺项，应补充精确主机或必要的专用后缀。禁止为解决单个资源失败而加入整个 CloudFront、AWS、Akamai 等共享后缀。

本次收窄是有意的：旧媒体集合中的游戏、小说、漫画、乐园等不再通过 GlobalMedia 匹配，但仍可能被通用 Proxy 等后续规则接住。这是规则集行为变更，不只是文件改名。

## 分类优先级

下面只定义业务分类之间的局部先后，不是可直接覆盖用户配置的完整规则顺序。

1. 保留各端已有的本地安全规则、局域网处理、用户例外和 Wi-Fi 场景；它们是否提前匹配应按用户意图保留。
2. Claude 在 AI 前；AI 在 Google / Microsoft 等公司分类前。
3. 若启用 Netflix、YouTube 专用路由，则放在 GlobalMedia 前；无需专用策略时可让它们指向同一个 GlobalMedia 策略。
4. GlobalMedia 在 Google / Apple 等公司分类前，避免 YouTube、Apple TV+ / Music 被公司组提前接走。
5. OneDrive、GitHub 在 Microsoft 前；APNS 在 Apple 前。
6. 业务分类在通用 Proxy / CN 及最终兜底之前；通用集合相互的既有顺序、IP 解析策略和最终兜底暂不调整。

IP 与域名文件分开发布。只有已明确维护的 Netflix、Telegram、Apple lite 等服务 IP 集合继续存在；不为媒体聚合自动加入整个云厂商 IP 或 ASN。APNS 是保留原混合规则的例外。

[custom/classification.json](../custom/classification.json) 的 `domain_priority` 是用来测试业务域名的参考顺序；不含 Wi-Fi、IP、APNS classical、CN、私有网络或最终兜底。报告中的 `winner: null` 只表示没有命中这些受测业务分类，**不是 DIRECT，也不是实际请求无法匹配任何规则**。

同一份参考顺序会生成 [Clash 业务规则片段](../examples/business-rules-clash.yaml) 和 [Surge 业务规则片段](../examples/business-rules-surge.conf)。它们不是完整配置，`POLICY_*` 必须映射到各自已有策略；不能覆盖当前整段规则。APNS、服务 IP、Wi-Fi 等不包含在这个域名片段里，接入时另行保留和检查。

## 自动防止分类退化

构建在发布前执行：

- **互斥检查**：GlobalMedia 与 Claude 上游域名基线、AI 不能有域名匹配范围交叉。不只比较字符串，还检查父后缀、子域名和根域名边界；例如错误加入 `+.com` 也会被发现。此项不对 Claude 的宽匹配补充规则宣称完全互斥。
- **包含检查**：Claude 上游基线必须被 AI 覆盖；Netflix、YouTube 必须被 GlobalMedia 覆盖。上游分类拆分或漏收时及时失败。完整 Claude classical 集合不受这个子集假设约束。
- **Claude 完整集合检查**：独立检查全部上游规则仍在，并强制保留两个域名后缀和 `claude` / `anthropic` 两个关键词；验证正反匹配样例。YAML / Surge 的完整条目集合必须一致，不能只检查上游基线。主配置仅留一个 RULE-SET 引用，位于 Wi-Fi 直连前；不发布不完整的 Claude MRS。
- **优先级检查**：记录 Google / AI、Google / YouTube、Apple / 媒体等合理交叉，验证参考小类先于大类。
- **域名回归检查**：验证 Claude、Gemini、Copilot、YouTube、Apple TV+、银行等典型域名；反向验证 Steam、小说、Disney 乐园和通用 CDN 随机子域不应命中媒体。
- **每组件检查**：每份服务源都必须可下载、可解码、满足最低条数和数量变化阈值。不会忽略下载失败的某个服务后继续发布残缺聚合。
- **精确选择检查**：Disney+ 白名单条目若从上游消失，要求人工审核；新增上游品牌域名不会自动进入媒体。

共享 CDN 若与 AI 出现新的交叉，构建停止等待审核，不自动删除整个范围，也不自动豁免。`--allow-large-change` 仅放行已审核的条数变化，不能绕过分类边界检查。边界测试不能证明所有未来域名都分类正确，仍需结合上游变动与实际连接日志审查。

结果保存在 [classification-audit.json](../metadata/classification-audit.json)。它验证的是规则内容和参考优先级，**不等于已经在客户端验证了网络连通、DNS、解锁或全部路由行为**。

## 如何长期维护

1. 增加服务：只修改 `sources.json` 的媒体组件清单；审查是否为公司大集合，必要时用精确 `select` 限定范围。
2. 修改例外：用 `custom/overrides.json` 做明确、可追踪的条目调整；删除一个条目不代表排除其父后缀的覆盖，分类检查会继续验证。
3. 新增样例：同步更新 `custom/classification.json`，把“这条不应再错分”的期望写成可执行检查。
4. 更新发布：继续每天 UTC+8 09:17 拉取固定上游快照，验证后生成 MRS / YAML / Surge LIST；失败保留上一版。
5. 接入客户端：先备份，保留各自策略和 Wi-Fi / 兜底，再替换对应规则订阅及检查业务规则顺序。Claude 改用 classical YAML / Surge LIST，更新 URL 与缓存路径后再移除主配置里的重复补充规则。

所有服务组件的原始文件保存在 `Sources/global_media_domain/`，精确来源 SHA、哈希、条数与筛选范围保存在 `metadata/sync-state.json`。旧 `category-entertainment` 原始文件已不再作为当前输入，历史版本可从 Git 恢复。
