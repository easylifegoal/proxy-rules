# Proxy Rules

个人维护的 Surge 与 Clash / Mihomo 分流规则，以及经过校验的上游同步工作流。

## 自动同步

[工作流与运行记录](https://github.com/easylifegoal/proxy-rules/actions/workflows/sync-rules.yml)

以现有规则清单为基准，共 19 组：MetaCubeX 17 组、Fake-IP 排除名单 1 组、手动维护的银行域名 1 组。
不上传节点、密码、UUID、私钥或完整代理配置，也不会自动修改任何客户端配置。

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
| AI、GitHub、Telegram、Netflix、PayPal、OneDrive、微软、Apple、私有域名、国内域名、国外域名 | MetaCubeX `meta/geo/geosite` |
| `global_media_domain` | MetaCubeX `category-entertainment`，沿用现有名单；除流媒体还包含游戏、小说等，不是纯视频集合 |
| 私有、中国、Telegram、Netflix IP | MetaCubeX `meta/geo/geoip` |
| Apple IP | MetaCubeX `meta/geo-lite/geoip/apple.mrs`，保留原来的 lite 来源 |
| `fakeipfilter_domain` | wwqgtxx/clash-rules `release/fakeip-filter.mrs`，更上游为 ShellCrash |
| `usbank_domain` | 本仓库 `custom/usbank.txt`，仅下面说明的六个银行域名 |

精确来源保存在 [sources.json](sources.json)。[NOTICE.md](NOTICE.md) 记录来源、许可及归属说明。

### 生成文件与订阅

| 路径 | 用途 |
| --- | --- |
| `Clash/<名称>.mrs` | Mihomo，`format: mrs`；`behavior` 对应 domain 或 ipcidr |
| `Clash/<名称>.yaml` | 可读 YAML，通常为 domain/ipcidr；**银行 YAML 保持原有 classical 格式** |
| `Text/<名称>.list` | Mihomo 的可读域名/IP 清单，不可直接当作 Surge RULE-SET |
| `Surge/<名称>.list` | Surge RULE-SET，不包含策略名称；IP 规则带 no-resolve |
| `Sources/*` | 未修改的上游 MRS 及其解码文本，用于审核与重新生成 |
| `metadata/sync-state.json` | 最后一次发布使用的源版本、哈希及条数，不是最近一次检查时间 |

例如 Netflix：

- [Clash MRS](https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/netflix_domain.mrs)
- [Clash YAML](https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/netflix_domain.yaml)
- [Surge RULE-SET](https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Surge/netflix_domain.list)

完整的 **provider 配置片段**见 [MRS 示例](examples/rule-providers-mrs.yaml)、[YAML 示例](examples/rule-providers-yaml.yaml)。保留自己的规则顺序、策略名称、节点及 DNS 设置，不要将片段覆盖成完整配置。
[Surge 示例](examples/surge-rules.conf) 中的 `POLICY` 必须替换；列表顺序只是清单顺序，不是建议的分流顺序。

`fakeipfilter_domain` 是 Mihomo 的 **DNS Fake-IP 排除名单**，不是路由策略，因此不生成 Surge 路由文件。它包含 Mihomo 的单层通配符，不能直接换成 Surge 的跨层通配符；其余规则若将来出现不能等价转换的模式，构建会停止，绝不静默扩大匹配范围。

跨格式生成以当前 **MRS 实际包含的规则**为基准。上游 classical 文件中可能额外包含的正则、关键词等不会被擅自加入，避免迁移时改变现有范围。未做自定义修改的 MRS 会原样发布，不重新压缩替换。

### 如何维护

1. 增减同步规则：编辑 `sources.json`，保留原始路径、behavior 和合理的最低条数。
2. 维护银行域名：仅编辑 `custom/usbank.txt`，会生成全部格式。`usbank` 是标准输出名；旧的 `BankOfAmerica` 文件名作为兼容别名同步生成，供旧订阅继续访问。
3. 其他自定义内容：编辑 `custom/overrides.json`，例如：

   ```json
   {"netflix_domain": {"add": ["+.example.com"], "remove": []}}
   ```

   上述只是语法示例，不表示 example.com 属于 Netflix。`remove` 是对 `Sources/<名称>.txt` 中条目的**精确删除**，不是排除任意子域名：若祖先后缀或更大 IP 网段仍在，访问仍可能匹配。需要例外路由时优先在主配置前面加规则。删除不存在的条目会报错，防止过期的自定义项被静默忽略。

### 本地验证和回退

依赖 Python 3.10+ 标准库，转换器固定为官方 Mihomo v1.19.32，并校验下载资产 SHA-256。安装脚本支持 Linux x86_64 和 macOS arm64。

```sh
python3 scripts/install_mihomo.py
python3 -m unittest discover -s tests -v
python3 scripts/sync_rules.py
python3 scripts/validate_generated.py
python3 scripts/sync_rules.py --pinned --check
```

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
