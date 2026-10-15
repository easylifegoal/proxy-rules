# Proxy Rules

个人维护的 Surge 与 Clash / Mihomo 分流规则，以及经过校验的上游同步工作流。

## 自动同步

[工作流与运行记录](https://github.com/easylifegoal/proxy-rules/actions/workflows/sync-rules.yml)

结合 Clash 与 Surge 的分类需求，共 23 组：MetaCubeX 派生分类 20 组（含服务清单聚合的 GlobalMedia）、APNS 1 组、Fake-IP 排除名单 1 组、手动维护的银行域名 1 组。
不上传节点、密码、UUID、私钥或完整代理配置，也不会自动修改任何客户端配置。
仓库中的 `Profiles/` 是去除连接信息、私人例外和 SSID 的规则合并片段；包含节点的完整配置只保存在用户自己的设备 / iCloud。

[长期分类方案](docs/classification-design.md) 说明当前规则边界、媒体服务清单、优先级与自动检查；[两端旧规则源对比](docs/source-comparison.md) 保留迁移前的审计快照。**构建完成不代表客户端已切换订阅**；各自策略、Wi-Fi 场景、规则顺序和兜底继续由原配置控制。

- **计划每天 09:17（北京时间 / 新加坡时间，UTC+8）更新**，也支持 Actions → Run workflow 手动运行。
- GitHub 定时任务不保证准点；长时间无仓库活动时可能暂停，请以 Actions 的实际成功记录为准。
- 首先固定每个上游分支的提交 SHA，再从同一个快照下载，避免一批文件混用不同版本。
- 全部下载、解析和转换成功才发布。空文件、损坏 MRS、少于清单最低条数、相较上次条数下降超过 20% 或增长超过 2 倍，都会阻止发布。
- 数量异常经人工检查后，可在手动运行时勾选 `allow_large_change`；最低条数和格式校验仍不能绕过。
- 只在输出内容变化时提交；仅上游重新构建、提交号变化不会产生空更新。同步失败时 GitHub 上保留上一次已发布版本。
- 不使用强制推送；若同步期间有人修改仓库，发布失败后需要重跑，不覆盖人的提交。

### 规则来源及范围

| 规则 | 来源 |
| --- | --- |
| AI、GitHub、Telegram、Netflix、PayPal、OneDrive、微软、Google、Apple、私有域名、国内域名、国外域名 | MetaCubeX `meta/geo/geosite` |
| `claude_domain` / `youtube_domain` | MetaCubeX `anthropic.mrs` / `youtube.mrs`，可单独路由；仍分别属于 AI / GlobalMedia 大集合 |
| `global_media_domain` | 在 `sources.json` 明确列出 20 个影音服务，同一 MetaCubeX 快照聚合；**不再使用 category-entertainment**，不引入游戏、小说或 AI 大分类；Disney+ 使用审核过的精确条目白名单 |
| 私有、中国、Telegram、Netflix IP | MetaCubeX `meta/geo/geoip` |
| Apple IP | MetaCubeX `meta/geo-lite/geoip/apple.mrs`，保留原来的 lite 来源 |
| `google_domain` | MetaCubeX `google.mrs`，**包含 YouTube**；不引入整份 Google/云平台 IP 集合，也不等同于旧 Surge Google 混合名单 |
| `apns` | QuixoticHeart/rule-set `ruleset/loon/apns.list`，保留域名、关键词、IPv4/IPv6 和 no-resolve；仅输出 classical YAML / 文本 / Surge |
| `fakeipfilter_domain` | wwqgtxx/clash-rules `release/fakeip-filter.mrs`，更上游为 ShellCrash |
| `usbank_domain` | 本仓库 `custom/usbank.txt`，仅下面说明的六个银行域名 |

精确来源保存在 [sources.json](sources.json)。[NOTICE.md](NOTICE.md) 记录来源、许可及归属说明。

### 生成文件与订阅

| 路径 | 用途 |
| --- | --- |
| `Clash/<名称>.mrs` | Mihomo，`format: mrs`；`behavior` 对应 domain 或 ipcidr；**APNS 不生成 MRS** |
| `Clash/<名称>.yaml` | 可读 YAML，通常为 domain/ipcidr；**银行与 APNS 使用 classical 格式** |
| `Text/<名称>.list` | 可读规范化数据；域名/IP 清单不能直接当作 Surge RULE-SET，APNS 为 classical 规则 |
| `Surge/<名称>.list` | Surge RULE-SET，不包含策略名称；IP 规则带 no-resolve |
| `Sources/*` | 未修改的上游 MRS / classical 原文，以及规范化文本，用于审核与重新生成 |
| `metadata/sync-state.json` | 最后一次发布使用的源版本、哈希及条数，不是最近一次检查时间 |
| `metadata/classification-audit.json` | 分类互斥、包含关系、允许的跨分类重叠，以及典型域名的建议匹配结果 |
| `Profiles/Clash.rules.yaml` | 可合并到现有 Mihomo 配置的 `rules` + `rule-providers`，含已映射的策略名称 |
| `Profiles/Surge.rules.conf` | 可合并到现有 Surge 配置的 `[Rule]`，含已映射的策略名称 |

### 两端规则配置

- [Clash 规则配置](Profiles/Clash.rules.yaml)：23 个 provider，22 组共享路由规则；Fake-IP 只供现有 DNS 配置引用。APNS 使用 YAML，其余使用 MRS。
- [Surge 规则配置](Profiles/Surge.rules.conf)：同样的 22 组路由名单，使用 Surge 文本规则。

两份都**不是独立可连接的完整配置**，不含节点、策略组定义、私人域名例外、内网 IP、SSID、DNS 或控制器凭据。合并时保留这些本地内容，不能直接覆盖完整文件。`custom/client-routing.json` 维护策略映射与顺序，每次构建自动生成；无需手改输出。

| 分类 | Clash 原有策略 | Surge 原有策略 |
| --- | --- | --- |
| Claude / AI | Claude / AI | Claude / AI |
| Netflix / YouTube / 其他媒体 | Netflix / GlobalMedia / GlobalMedia | 全部 GlobalMedia |
| Google | Google | Google |
| OneDrive / GitHub / 微软 | OneDrive / GitHub / Microsoft | 全部 Proxy |
| APNS / Apple | Apple / Apple | APNS / Apple |
| PayPal / 银行 / Telegram | PayPal / USBank / Proxy | Paypal / USBank / Proxy |
| 兜底 | 80、443、22 → Final，其余 DIRECT | Proxy，保留 dns-failed |

分类覆盖统一，不强行统一两端策略或 Wi-Fi 行为。Claude 在 AI 之前；Netflix / YouTube 在 GlobalMedia 之前；媒体在 Google / Apple 之前；OneDrive / GitHub 在微软之前；APNS 在 Apple 之前。这些顺序均有自动测试。Clash 保留中国 IP 规则可触发解析的语义；Surge 的 IP 规则条目保留 no-resolve，因此两端不能宣称所有解析行为完全相同。

Claude 另有用户明确要求保留的四条宽匹配规则：`claude-api.com` / `claudecontentmoderation.com` 域名后缀，以及 `claude` / `anthropic` 关键词，均指向 `Claude`，放在 Claude 上游集合和通用 AI / 媒体 / 地理分类之前。它们由 `custom/client-routing.json` 的 `claude_guards` 同时生成到两端主配置片段，并有防漏测验。关键词会匹配任何含该词的域名，包括第三方站点；这是主动选择的更宽路由范围，不是官方域名归属认证，也不能识别域名不含这些词的所有相关服务。关键词不支持 MRS，因此保留为主配置规则，不混入 `claude_domain.mrs`。本仓库分类互斥 / 子集检查针对上游域名集合，不代表宽匹配例外与其他业务绝不重叠。

完整 Surge 配置中的家庭 Wi-Fi 直连例外应放在银行 / APNS、Claude 四条宽匹配规则及 `claude_domain` 规则集之后，确保 Claude 在家庭 Wi-Fi 下也优先走 Claude 策略；公开片段已标明插入位置。公司 Wi-Fi 例外仍在 Claude / AI / PayPal 后、媒体等通用规则前。具体 SSID 不进入本仓库。此处只改变 Claude 与家庭 Wi-Fi 的先后关系，IP 查询等其他个人例外仍保留原来的顺序。Clash 的 QUIC 策略、个人例外及 DNS 继续由私有完整配置管理。

Clash provider 缓存使用 `./providers/proxy-rules/`，避免迁移后复用旧娱乐分类缓存。两份公开配置在测试时临时配上仅指向 DIRECT 的占位策略组，再执行原生语法校验；不会连接真实代理或重载用户配置。Linux CI 校验 Mihomo，Surge 校验需在安装 Surge 的 macOS 本地执行。

例如 Netflix：

- [Clash MRS](https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/netflix_domain.mrs)
- [Clash YAML](https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/netflix_domain.yaml)
- [Surge RULE-SET](https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Surge/netflix_domain.list)

完整的 **provider 配置片段**见 [MRS 示例](examples/rule-providers-mrs.yaml)、[YAML 示例](examples/rule-providers-yaml.yaml)。保留自己的规则顺序、策略名称、节点及 DNS 设置，不要将片段覆盖成完整配置。
[Surge 示例](examples/surge-rules.conf) 中的 `POLICY` 必须替换；列表顺序只是清单顺序，不是建议的分流顺序。

需要参考长期业务分类的先后关系时，使用 [Clash 业务顺序片段](examples/business-rules-clash.yaml) / [Surge 业务顺序片段](examples/business-rules-surge.conf)。两份由同一份分类约束生成，只含业务域名规则，不能替换完整配置；策略占位符需映射到各自已有策略。

MRS 示例是 **MRS 优先**，其中 APNS 自动使用 `behavior: classical`、`format: yaml`。MRS 不支持关键词规则，不能把 APNS 的域名/IP 部分单独转成 MRS 就声称完整等价。APNS 的 YAML 与 Surge 文件包含同一套规则。

`fakeipfilter_domain` 是 Mihomo 的 **DNS Fake-IP 排除名单**，不是路由策略，因此不生成 Surge 路由文件。它包含 Mihomo 的单层通配符，不能直接换成 Surge 的跨层通配符；其余规则若将来出现不能等价转换的模式，构建会停止，绝不静默扩大匹配范围。

MetaCubeX 跨格式生成以当前 **MRS 实际包含的规则**为基准。其他旧 classical 名单中的正则、关键词、进程、User-Agent 和 ASN 规则不会自动合并；这不是旧 Surge 名单的逐条镜像，差异详见对比文档。未做自定义修改的 MRS 会原样发布，不重新压缩替换。

APNS 是显式的 classical 例外。目前仅接受两端共有的 `DOMAIN`、`DOMAIN-SUFFIX`、`DOMAIN-KEYWORD`、`IP-CIDR`、`IP-CIDR6` 及 IP 的 `no-resolve`。遇到新增的未知类型、选项或夹带策略名会阻止发布，不能静默丢弃。

GlobalMedia 聚合时保留每个组件的原始 MRS、解码文本、SHA 与条数。每个组件分别执行格式和数量检查，避免一个服务丢失被其他服务新增掩盖。服务清单不会随娱乐大分类自动扩张。Disney+ 白名单中若有条目从上游消失，构建报错；新增条目需要审核后补入。

`custom/classification.json` 定义分类约束：媒体与 Claude / AI 不得交叉（包括父后缀覆盖）；Claude 必须属于 AI，Netflix / YouTube 必须属于媒体集合。合理的 Google / Apple 等交叉被记录并检查建议优先级。分类失败与数量异常分开，`--allow-large-change` **不能跳过分类检查**。

### 如何维护

1. 增减同步规则：编辑 `sources.json`，保留原始路径、behavior 和合理的最低条数。
2. 维护银行域名：仅编辑 `custom/usbank.txt`，会生成全部格式。`usbank` 是标准输出名；旧的 `BankOfAmerica` 文件名作为兼容别名同步生成，供旧订阅继续访问。
3. 其他自定义内容：编辑 `custom/overrides.json`，例如：

   ```json
   {"netflix_domain": {"add": ["+.example.com"], "remove": []}}
   ```

   上述只是语法示例，不表示 example.com 属于 Netflix。`remove` 是对 `Sources/<名称>.txt` 中条目的**精确删除**，不是排除任意子域名：若祖先后缀或更大 IP 网段仍在，访问仍可能匹配。需要例外路由时优先在主配置前面加规则。删除不存在的条目会报错，防止过期的自定义项被静默忽略。

4. 维护媒体服务：编辑 `global_media_domain.inputs`。每项必须指定原始路径和最低条数；`select` 为可选的精确条目白名单，未列入的条目不会自动导入。不要用整份娱乐、公司或云厂商集合代替服务列表。
5. 增加边界/回归检查：编辑 `custom/classification.json`，添加代表性域名、禁止匹配域名或分类关系。共享基础设施出现跨类时先审核，不自动删除整段 CDN。

构建会清理旧状态中登记、但已不再生成的文件；只允许删除内容哈希未改变的生成文件，手动修改过的旧文件会阻止清理。历史版本仍可从 Git 找回。

### 本地验证和回退

依赖 Python 3.10+ 标准库，转换器固定为官方 Mihomo v1.19.32，并校验下载资产 SHA-256。安装脚本支持 Linux x86_64 和 macOS arm64。

```sh
python3 scripts/install_mihomo.py
python3 -m unittest discover -s tests -v
python3 scripts/sync_rules.py
python3 scripts/validate_generated.py
python3 scripts/sync_rules.py --pinned --check
```

macOS 已安装 Surge 时，可附加只读语法校验（不切换或重载正在使用的配置）：

```sh
python3 scripts/validate_generated.py --surge-cli /Applications/Surge.app/Contents/Applications/surge-cli
```

校验同时比较 Surge、YAML 与规范化文本的匹配条目；MRS 通过编译/解码往返验证。测试的是文件及转换，不代表已经验证所有业务流量或改变了客户端行为。

`--pinned --check` 使用最后发布的上游 SHA 重新验证，不写文件；首次生成后才能运行。回退可对错误发布提交执行 `git revert`；如果错误仍存在于上游，应先在 Actions 暂停工作流，避免下一次同步再次引入。

这里只自动跟随上游，不会根据用户流量自动发现新域名，也不会替代上游维护者的分类判断。

## usbank

面向 Bank of America（美国银行）及 Merrill / Merrill Edge（美林投资）的域名规则集，Surge、Clash YAML 与 Mihomo MRS 三份文件覆盖相同的六个根域名及其子域名。

| 文件 | 格式 |
| --- | --- |
| [Surge/usbank.list](Surge/usbank.list) | Surge `RULE-SET` |
| [Clash/usbank.yaml](Clash/usbank.yaml) | Clash / Mihomo `classical` YAML rule-provider |
| [Clash/usbank.mrs](Clash/usbank.mrs) | Mihomo `domain` MRS 二进制规则集 |

### 覆盖范围

| 域名 | 收录说明 |
| --- | --- |
| `bankofamerica.com` | Bank of America 银行业务域名及其子域名 |
| `bofa.com` | Bank of America 相关业务域名及其子域名 |
| `bac.com`、`baml.com` | 社区 BOA 分组中的补充域名；未确认每个零售银行功能都会访问 |
| `ml.com`、`merrilledge.com` | Merrill / Merrill Edge 投资服务及其子域名 |

每条后缀规则同时匹配根域名与子域名。规则集不绑定节点或直连策略，由主配置决定。

本规则集未经过 BOA App 全流程抓包验证，不能保证覆盖登录、验证码、转账或其他功能使用的全部第三方请求。共享服务域名应在实际连接记录确认用途后按需补充。当前未加入宽泛的 `DOMAIN-KEYWORD`、其他银行或支付平台规则。

### Surge 用法

将以下规则加入现有配置的 `[Rule]` 段，置于通用分流规则与 `FINAL` 之前：

```ini
RULE-SET,https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Surge/usbank.list,美国银行
```

将 `美国银行` 替换为你已有的节点或策略组名称；如需直连，则使用 `DIRECT`。

### Clash / Mihomo 用法

将以下内容合并到现有的 `rule-providers` 与 `rules` 中。不要重复创建同名顶层字段；将此 `RULE-SET` 放在可能提前匹配的通用规则与 `MATCH` 之前。

#### Mihomo MRS

使用支持 MRS 的 Mihomo / Clash Meta 内核时，可以直接订阅：

```yaml
rule-providers:
  usbank:
    type: http
    behavior: domain
    format: mrs
    url: https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/usbank.mrs
    path: ./ruleset/usbank.mrs
    interval: 86400

rules:
  - RULE-SET,usbank,美国银行
```

MRS 由 Mihomo 官方工具编译，使用 `+.域名` 保持根域名与所有层级子域名的匹配语义。这里必须使用 `behavior: domain`。不支持 MRS 的客户端使用下面的 YAML 格式；Surge 继续使用 `.list`。

#### Clash YAML

与上面的 MRS 配置二选一：

```yaml
rule-providers:
  usbank:
    type: http
    behavior: classical
    format: yaml
    url: https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/usbank.yaml
    path: ./ruleset/usbank.yaml
    interval: 86400

rules:
  - RULE-SET,usbank,美国银行
```

将 `美国银行` 替换为现有策略名称。以上仅为配置片段；规则文件本身不是节点订阅或完整的 Clash 配置。

### 来源与维护

- [社区 US_Bank.list 的 Bank of America 分组](https://gist.github.com/sarkrui/2157553656e8e6a48ee94ebf94ef9460)：六个域名后缀的初始来源。
- [Bank of America 官网](https://www.bankofamerica.com/)：银行与 Merrill 服务入口。
- [Surge 域名规则文档](https://manual.nssurge.com/rules/domain.html)及[规则集文档](https://manual.nssurge.com/rules/ruleset.html)。
- [Mihomo 规则集合文档](https://wiki.metacubex.one/config/rule-providers/)。

新增或移除域名时编辑 `custom/usbank.txt`，由上述工作流统一生成 Surge、Clash YAML 与 MRS。应根据连接记录确认需求；域名归属与功能覆盖需分开判断。不要直接修改生成文件，下一次同步会覆盖。
