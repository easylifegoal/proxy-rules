# Sources, attribution and licensing

This repository mirrors and converts public routing data. It is not an official
MetaCubeX, Mihomo, Surge, Netflix, Anthropic, or bank service.

## Upstream rule data

| Manifest source | Repository / publication branch | Upstream license |
| --- | --- | --- |
| `metacubex` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat), `meta` | [GPL-3.0](https://github.com/MetaCubeX/meta-rules-dat/blob/master/LICENSE) |
| `fakeip` | [wwqgtxx/clash-rules](https://github.com/wwqgtxx/clash-rules), `release` | [GPL-3.0](https://github.com/wwqgtxx/clash-rules/blob/master/LICENSE) |
| `apns` | [QuixoticHeart/rule-set](https://github.com/QuixoticHeart/rule-set), `ruleset/loon/apns.list` | [GPL-3.0](https://github.com/QuixoticHeart/rule-set/blob/master/LICENSE) |

The GPL version 3 text is preserved at [LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt).
The upstream repositories aggregate additional sources, whose original notices
and terms are not replaced by this file. See their READMEs and build workflows
for the complete provenance chain, including v2fly/domain-list-community,
Loyalsoldier, blackmatrix7/ios_rule_script and juewuy/ShellCrash.

`Sources/*.mrs` and `Sources/apns.list` are unmodified upstream files (including
any original comments). `Sources/*.txt` expose their decoded/normalized
contents. `metadata/sync-state.json` records the exact upstream commit, raw URL,
SHA-256 and entry counts for the last published build. `Clash`, `Text` and `Surge`
files are generated representations, with optional explicit modifications from
`custom/overrides.json`. For unchanged input, the published MRS is byte-for-byte
identical to the upstream binary. Generated representations of upstream rules
remain subject to the upstream GPL terms and any applicable original notices.
The curated GlobalMedia bundle combines the explicitly listed MetaCubeX service
inputs in `sources.json`. Each raw component is retained under
`Sources/global_media_domain/`, with provenance and any explicit Disney+ selection
recorded in `metadata/sync-state.json`. Its output MRS is compiled from the union,
not represented as an unchanged upstream binary. Selection does not replace the
original data license or imply a new license grant.
The APNS classical set is kept intact across YAML and Surge outputs; no partial
MRS representation is published. The source-comparison document cites additional
legacy rule sources for comparison only; it does not mirror those full datasets.

The bank rules predate this synchronization workflow. Their initial community
source, scope and limitations remain documented in the README; no additional
license grant is asserted for third-party contributions to that list.

## Build code and tools

The newly added `scripts/`, `tests/` and `.github/workflows/` synchronization code
is provided under GPL-3.0-only, as identified by SPDX headers where applicable.
Mihomo is downloaded from its official release solely as a build tool; binaries
are not committed here. Its [source and license](https://github.com/MetaCubeX/mihomo)
remain available upstream. Tool version and compressed-asset SHA-256 are pinned
in `scripts/install_mihomo.py`.

Only public rules and build metadata belong here. Do not commit full user proxy
profiles, passwords, node UUIDs, private keys, or access tokens.
