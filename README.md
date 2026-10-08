# Proxy Rules

个人维护的 Surge 与 Clash / Mihomo 分流规则。

## Bank of America / Merrill

面向 Bank of America（美国银行）及 Merrill / Merrill Edge（美林投资）的域名规则集，两种格式包含相同的六条 `DOMAIN-SUFFIX` 规则。

| 文件 | 格式 |
| --- | --- |
| [Surge/BankOfAmerica.list](Surge/BankOfAmerica.list) | Surge `RULE-SET` |
| [Clash/BankOfAmerica.yaml](Clash/BankOfAmerica.yaml) | Clash / Mihomo `classical` YAML rule-provider |

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
RULE-SET,https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Surge/BankOfAmerica.list,美国银行
```

将 `美国银行` 替换为你已有的节点或策略组名称；如需直连，则使用 `DIRECT`。

### Clash / Mihomo 用法

将以下内容合并到现有的 `rule-providers` 与 `rules` 中。不要重复创建同名顶层字段；将此 `RULE-SET` 放在可能提前匹配的通用规则与 `MATCH` 之前。

```yaml
rule-providers:
  BankOfAmerica:
    type: http
    behavior: classical
    format: yaml
    url: https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/BankOfAmerica.yaml
    path: ./ruleset/BankOfAmerica.yaml
    interval: 86400

rules:
  - RULE-SET,BankOfAmerica,美国银行
```

将 `美国银行` 替换为现有策略名称。以上仅为配置片段；规则文件本身不是节点订阅或完整的 Clash 配置。

### 来源与维护

- [社区 US_Bank.list 的 Bank of America 分组](https://gist.github.com/sarkrui/2157553656e8e6a48ee94ebf94ef9460)：六个域名后缀的初始来源。
- [Bank of America 官网](https://www.bankofamerica.com/)：银行与 Merrill 服务入口。
- [Surge 域名规则文档](https://manual.nssurge.com/rules/domain.html)及[规则集文档](https://manual.nssurge.com/rules/ruleset.html)。
- [Mihomo 规则集合文档](https://wiki.metacubex.one/config/rule-providers/)。

新增或移除域名时应同步修改两种格式，并根据连接记录确认需求；域名归属与功能覆盖需分开判断。
