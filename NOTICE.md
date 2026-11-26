# Sources, attribution and licensing

This repository mirrors and converts public routing data. It is not an official
MetaCubeX, Mihomo, Surge, Netflix, Anthropic, or bank service.

## Upstream rule data

| Manifest source | Repository / publication branch | Upstream license |
| --- | --- | --- |
| `metacubex` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat), `meta` | [GPL-3.0](https://github.com/MetaCubeX/meta-rules-dat/blob/master/LICENSE) |
| `blackmatrix7` (Apple common projection) | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script), `master/rule/Surge/Apple/Apple_All_No_Resolve.list` | [Upstream GPL v2 text](https://github.com/blackmatrix7/ios_rule_script/blob/master/LICENSE) |
| `fakeip` | [wwqgtxx/clash-rules](https://github.com/wwqgtxx/clash-rules), `release` | [GPL-3.0](https://github.com/wwqgtxx/clash-rules/blob/master/LICENSE) |
| `apns` (retired 2026-11-27; historical attribution) | [QuixoticHeart/rule-set](https://github.com/QuixoticHeart/rule-set), `ruleset/loon/apns.list` | [GPL-3.0](https://github.com/QuixoticHeart/rule-set/blob/master/LICENSE) |

The GPL version 3 text is preserved at [LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt).
The Apple upstream's GPL version 2 text is preserved verbatim at
[LICENSES/GPL-2.0.txt](LICENSES/GPL-2.0.txt). Apple source and derived data remain
under their upstream terms; the GPL-3.0-only code notice does not relicense them.
The upstream repositories aggregate additional sources, whose original notices
and terms are not replaced by this file. See their READMEs and build workflows
for the complete provenance chain, including v2fly/domain-list-community,
Loyalsoldier, blackmatrix7/ios_rule_script and juewuy/ShellCrash.

`Sources/*.mrs` are unmodified upstream files (including any original comments). `Sources/*.txt` expose their decoded/normalized
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
The APNS set and independent route were retired on 2026-11-27. Earlier APNS files
and their original licensing notices remain recoverable in Git history. The source-comparison document cites additional
legacy rule sources for comparison only; it does not mirror those full datasets.
Claude's upstream MRS remains unmodified under `Sources/`. Its published classical
YAML and Surge sets merge the decoded upstream domains with explicit local suffix
and keyword additions from `custom/overrides.json`. The broad keywords express a
routing preference, not certification of domain ownership. No partial Claude MRS
output is published; the previous output remains recoverable in Git history.

The complete Apple upstream file, including its comments, is retained as
`Sources/apple_no_resolve.list`. Its modified shared exports preserve domain,
keyword and no-resolve IP entries. Both clients exclude the same reviewed
PROCESS-NAME and USER-AGENT rules, retained in `Sources/apple_no_resolve.excluded.list`
and counted in the build metadata. These exports are a documented projection,
not an unmodified copy of the original full rule set. They do not incorporate
the retired MetaCubeX Apple sets; older files remain in Git history.

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
