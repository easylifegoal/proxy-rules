# Clash / Surge 规则源对比与统一范围

> 这是第一版 21 组规则构建时的历史对比快照。随后按长期分类要求升级为 23 组：GlobalMedia 改为明确影音服务聚合，并新增 Claude / YouTube 独立分类。下文“统一版本”描述第一版，不是当前 GlobalMedia 配方。当前方案见 [长期分类设计](classification-design.md)。客户端配置在这两次仓库建设中均未修改。

核对日期：2026-10-14。核对对象是 iCloud 中的 Clash `Mixed.yaml` 与 Surge `Mixed.conf` 所引用的公开规则源，不是客户端当前缓存内容或流量日志。本报告不上传完整配置、节点、账号、SSID 或内网信息。

## 结论

两端过去不仅格式不同，**来源、分类边界和规则类型也不同**：Clash 主要使用 MetaCubeX 的 domain / ipcidr MRS；Surge 主要使用 blackmatrix7 的混合规则，另有 EAlyce AI、QuixoticHeart APNS、GetSomeFries 中国 ASN。

仓库现在提供一套共同规则内容，分别构建 Mihomo MRS / YAML 与 Surge RULE-SET。主体选用 MetaCubeX；保留现有银行域名、Fake-IP 来源；补齐 Google 与 APNS。不是把所有旧名单简单取并集，也不是逐条复刻旧 Surge 行为。

**本次只改仓库，没有替换任何客户端的订阅 URL、规则顺序、策略、Wi-Fi 场景或兜底。** 两端今后订阅同一规则，不代表在不同 DNS、IP 解析状态或规则顺序下必然走同一节点。

## 分类差异

下表条数为本次公开源快照去掉空行与注释后的统计；MetaCubeX 使用 MRS 解码、规范化后的条数。域名后缀可覆盖大量子域名，MRS 还会合并冗余项，所以条数不是“效果排名”，也不表示条数相减就是漏掉的网站数。

| 类别 | Clash 原来源与内容 | Surge 原来源与内容 | 仓库统一版本 / 差异处理 |
| --- | --- | --- | --- |
| AI | MetaCubeX `category-ai-!cn`，189 条域名 | EAlyce `OpenAI.list`，101 条：97 域名、3 IP、1 ASN；并非仅 OpenAI | 使用共同的 MetaCubeX AI；不合并整个 ASN 或旧名单的共享服务大后缀 |
| GlobalMedia | MetaCubeX `category-entertainment`，2,123 条域名 | blackmatrix7，2,335 条混合规则，含 Claude / Anthropic、IP、关键词、User-Agent、进程与 URL 正则 | 保留 MetaCubeX 娱乐类：含 YouTube，也含游戏、小说，不是纯视频；AI 单列 |
| Google | 有策略组，但未引用独立 Google 规则集 | blackmatrix7，703 条：685 域名、5 关键词、5 IP、5 进程、3 User-Agent | 新增 MetaCubeX `google_domain`，1,049 条域名；**包括 YouTube**，与旧 Google（排除 YouTube）不完全同范围 |
| APNS | 未独立配置 APNS 集合 | QuixoticHeart，13 条：3 域名、1 关键词、5 IPv4、4 IPv6 | 原来源全量保留，生成相同内容的 classical YAML / Surge 文件，不提供不完整的 MRS |
| PayPal | MetaCubeX，245 条域名 | blackmatrix7，248 条：246 域名、1 关键词、1 User-Agent | 统一为 MetaCubeX 域名集合；不会自动加回关键词和 User-Agent |
| GitHub | MetaCubeX，65 条域名 | blackmatrix7，31 条：30 域名、1 关键词 | 统一为 MetaCubeX；映射到哪个策略组仍由各客户端决定 |
| Apple | MetaCubeX，1,789 条域名 + 10 条 lite IP | blackmatrix7，1,616 条：1,560 域名、7 关键词、13 IP、23 User-Agent、13 进程 | 统一为 MetaCubeX 域名 + 原有 lite IP；APNS 另列 |
| Netflix / Telegram | 分别有独立域名和 IP 集合：24+122、21+12 条 | 没有独立引用同名集合，部分内容被媒体 / Proxy 集合覆盖 | 仓库均生成双端版本，是否单独映射专用策略不强制 |
| OneDrive / Microsoft | 独立 MetaCubeX 集合，16 / 747 条域名 | 没有独立引用，部分内容在 Proxy 集合中 | 两端都提供这两个分类，仍保留各自策略体系 |
| 国外通用 | MetaCubeX `geolocation-!cn`，27,188 条域名 | blackmatrix7 Proxy，6,970 条：6,836 域名、26 关键词、100 IP、8 User-Agent | 统一采用 `geolocation-!cn`；不是旧 Proxy 混合规则的等价复制 |
| 国内 | MetaCubeX `cn_domain` 110,821 条 + `cn_ip` 9,609 条 | blackmatrix7 China，3,752 条；另加 GetSomeFries 5,076 条中国 ASN | 统一提供 MetaCubeX 域名 / CIDR；**没有将旧 ASN 动态范围转换或混入 CIDR** |
| 局域网 | MetaCubeX private，130 条域名 + 18 条 IP | Surge 内置 `LAN`，内容随客户端版本变化 | 公共 private 集合有双端版本；内置 LAN 不是它的字节等价物 |
| 银行 | 本仓库旧 `BankOfAmerica.mrs` URL | 本仓库 `usbank.list` | 已同源：6 个银行 / 美林根域名及子域名；旧文件名继续兼容 |
| Fake-IP 排除 | wwqgtxx，121 条 Mihomo DNS 模式 | 没有对应路由集合 | 仅供 Mihomo DNS，不伪造 Surge 路由替代品 |

## 需要特别知道的区别

### 1. AI 不应通过“大并集”统一

旧 EAlyce AI 名单不仅有 Claude、OpenAI 等，还包含 `IP-ASN,20473`，以及 auth0、stripe、sentry 等共享服务的宽泛后缀。若把整个旧名单合并进共同 AI 集合，会让这些基础设施上的其他业务也可能命中 AI 策略。

统一版跟随 MetaCubeX 的 AI 分类；它仍包含服务所需的部分第三方域名，并不意味着完全没有共享基础设施。旧配置中手写的 Claude 优先规则属于主配置，本次没有抽取、删除或迁移。

### 2. GlobalMedia 不是同一个集合的不同格式

旧 Surge GlobalMedia 实际有 Claude / Anthropic 规则；当前 MetaCubeX 娱乐类没有这些名称。统一版不把 AI 加到媒体分类。不过 `category-entertainment` 本身还覆盖游戏、小说等，不能称为“只含流媒体”。

MetaCubeX Google 包含 YouTube，GlobalMedia 也包含 YouTube；以后若希望 YouTube 继续走 GlobalMedia，应让媒体规则先匹配。Netflix 等更细的分类亦应在宽泛集合之前。**这里只提示重叠，不重新排列用户配置。**

### 3. Google 的补齐是共同域名分类，不是照搬旧混合规则

新增 `google_domain` 使用 MetaCubeX 实际 MRS 内容。旧 Surge Google 中 5 条 IP、5 条关键词、5 条进程和 3 条 User-Agent 不在该 domain 集合里。

本次没有另外订阅整份 Google / Google Cloud IP 集合，以免把范围扩大到大量云托管业务；也没有把进程或 User-Agent 强行改写成域名。是否另保留这些旧端侧例外，可在未来切换订阅时决定。

### 4. APNS 必须保留关键词，因此采用 classical

原名单的 13 条全部保留，包含 `no-resolve`。其中 `DOMAIN-KEYWORD` 不能装进 MRS，不能只输出域名/IP 部分然后声称“相同”。因此：

- Clash / Mihomo 使用 `Clash/apns.yaml`，`behavior: classical`。
- Surge 使用 `Surge/apns.list`。
- `Sources/apns.list` 留存未经修改的原文；`Sources/apns.txt` 为规范化版本。
- MRS 优先示例中，这一项自动回退 YAML。

原名单包含较宽的 `akadns.net` 后缀；这次为保持既有 APNS 规则范围，未擅自缩窄。未来若需精细化，应单独验证再改共同源。

### 5. 没有静默“折损转换”旧 Surge 全部规则

多数共同分类以 **MetaCubeX MRS 已编码的内容**为基准，而不是把旧 blackmatrix7 classical 文件截成 MRS。旧名单中的 User-Agent、进程、关键词、URL 正则及 ASN 并未被当作等价条目混入。

APNS 是显式、完整的 classical 例外。构建器仅接受已验证的共享类型；未知规则会使构建失败。Mihomo 单层 `*` 通配符不能简单映射为 Surge 跨层 `*`；遇到不能等价表达的模式同样失败，不扩大匹配范围。

## 更新链路

- 共同主来源：MetaCubeX 发布分支 `meta`；其构建继续聚合 v2fly/domain-list-community、Loyalsoldier、blackmatrix7 等。MetaCubeX 不是所有域名的最初维护者，也不是完全独立于旧 Surge 来源。
- APNS：QuixoticHeart 的 `ruleset` 发布分支；Fake-IP：wwqgtxx 的 `release`；银行：本仓库手动清单。
- 每次本仓库构建先固定各上游提交 SHA，然后从同一快照生成双端文件。默认每天 UTC+8 09:17 检查，变化才提交；格式/数量异常则不发布。
- 规则数据内容同步，不自动修改主配置，也不自动决定路由策略。

## 可核对的来源快照

共同源的准确 URL、SHA-256、条数见 [sync-state.json](../metadata/sync-state.json)。以下为本次旧源对比快照，未来上游更新后条数可能变化：

| 来源 | 提交 / 路径 |
| --- | --- |
| MetaCubeX | `9c8e9f56b6ffadab05bfc933011b2bfc2f4f8288`，`geo/geosite/*.mrs`、`geo/geoip/*.mrs`、`geo-lite/geoip/apple.mrs` |
| wwqgtxx | `cf4282f8b02e23de0373b1ebfeb8f9a286241ad9`，`fakeip-filter.mrs` |
| EAlyce | [`559d26fcbd7de02aac1371f6719a72a85e71eb3e` / `Rule/OpenAI.list`](https://github.com/EAlyce/conf/blob/559d26fcbd7de02aac1371f6719a72a85e71eb3e/Rule/OpenAI.list) |
| QuixoticHeart | [`80344839932c604b1c780a51c8fb8341d28a5729` / `loon/apns.list`](https://github.com/QuixoticHeart/rule-set/blob/80344839932c604b1c780a51c8fb8341d28a5729/loon/apns.list) |
| blackmatrix7 | [`d8363caa2c1e47fb735615316032bed3f475ee57` / `rule/Surge`](https://github.com/blackmatrix7/ios_rule_script/tree/d8363caa2c1e47fb735615316032bed3f475ee57/rule/Surge)：`PayPal/PayPal.list`、`GlobalMedia/GlobalMedia_All_No_Resolve.list`、`Google/Google.list`、`Apple/Apple_All_No_Resolve.list`、`GitHub/GitHub.list`、`Proxy/Proxy_All_No_Resolve.list`、`China/China_All_No_Resolve.list` |
| GetSomeFries | [`b4aa767bcbc4d39bea5b549a3277a00517891d1e` / `ruleset/ASN.China.list`](https://github.com/VirgilClyne/GetSomeFries/blob/b4aa767bcbc4d39bea5b549a3277a00517891d1e/ruleset/ASN.China.list) |

格式参考：[Mihomo rule-providers](https://wiki.metacubex.one/config/rule-providers/)、[Surge RULE-SET](https://manual.nssurge.com/rules/ruleset.html)、[Surge 域名匹配](https://manual.nssurge.com/rules/domain.html)。共同数据的来源和许可另见 [NOTICE.md](../NOTICE.md)。
