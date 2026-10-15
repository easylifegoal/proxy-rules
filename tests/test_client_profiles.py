# SPDX-License-Identifier: GPL-3.0-only
import copy
import json
from pathlib import Path
import unittest

from scripts.client_profiles import (FALLBACK, QUIC_RULE, TEST_TEMPLATE_VALUES, build_profiles,
                                     normalize_surge_rule, profile_entries, render_profiles,
                                     required_policies, validate_routing)
from scripts.sync_rules import surge_rules, validate_manifest

ROOT = Path(__file__).resolve().parents[1]


class ClientProfileTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "sources.json").read_text())
        self.routing = json.loads((ROOT / "custom/client-routing.json").read_text())
        self.contract = json.loads((ROOT / "custom/classification.json").read_text())

    def build(self, templates=False):
        return build_profiles(self.manifest, self.routing, self.contract,
                              TEST_TEMPLATE_VALUES if templates else None)

    def test_only_one_common_source_is_allowed(self):
        self.assertEqual(set(self.routing), {"schema_version", "policy_groups", "common", "surge_wifi"})
        for client in ("clash", "surge"):
            routing = copy.deepcopy(self.routing)
            routing[client] = copy.deepcopy(routing["common"])
            with self.assertRaisesRegex(ValueError, "One common"):
                validate_routing(self.manifest, routing, self.contract)

    def test_all_rules_are_equivalent_in_order_policy_and_options(self):
        for templates in (False, True):
            clash, surge = self.build(templates)
            self.assertEqual(clash["rules"], [normalize_surge_rule(r, self.manifest) for r in surge if not r.startswith("SUBNET,")])
            self.assertEqual(len(clash["rules"]), 37 if templates else 36)
            self.assertEqual(len(surge), 39 if templates else 36)
            self.assertEqual(required_policies(clash["rules"]), required_policies(surge))

    def test_private_settings_and_dns_rule_not_routed(self):
        clash, surge = self.build()
        self.assertEqual(set(clash), {"rules", "rule-providers"})
        self.assertEqual(len(clash["rule-providers"]), 23)
        self.assertFalse(any("fakeipfilter" in r for r in clash["rules"] + surge))
        for p in clash["rule-providers"].values():
            self.assertTrue(p["url"].startswith("https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/"))
            self.assertTrue(p["path"].startswith("./providers/proxy-rules/"))

    def test_formats_bank_alias_and_cache_versions(self):
        clash, surge = self.build()
        providers = clash["rule-providers"]
        for name in ("claude_domain", "apns"):
            self.assertEqual((providers[name]["behavior"], providers[name]["format"]), ("classical", "yaml"))
        self.assertTrue(providers["usbank_domain"]["url"].endswith("/usbank.mrs"))
        self.assertTrue(any("/usbank.list,USBank" in r for r in surge))
        self.assertTrue(providers["claude_domain"]["url"].endswith("/claude_domain.yaml?v=classical-v1"))
        self.assertTrue(providers["cn_ip"]["url"].endswith("/cn_ip.mrs?v=resolve-v1"))
        self.assertTrue(any("/cn_ip.list?v=resolve-v1,DIRECT" in r for r in surge))

    def test_claude_complete_set_is_single_and_precedes_generic_rules(self):
        clash, _ = self.build()
        rules = clash["rules"]
        claude = "RULE-SET,claude_domain,Claude"
        self.assertEqual(rules.count(claude), 1)
        for name in ("ai", "global_media_domain", "geolocation-!cn"):
            target = next(r for r in rules if r.startswith(f"RULE-SET,{name},"))
            self.assertLess(rules.index(claude), rules.index(target))
        self.assertFalse(any(r.startswith(("DOMAIN-SUFFIX,claude", "DOMAIN-KEYWORD,claude,",
                                          "DOMAIN-KEYWORD,anthropic,")) for r in rules))

    def test_shared_policy_mapping_has_no_direct_node_targets(self):
        clash, surge = self.build()
        for rules in (clash["rules"], surge):
            self.assertIn("DOMAIN-SUFFIX,nodeseek.com,Nodeseek", rules)
            self.assertIn("DOMAIN-KEYWORD,n26,N26", rules)
            self.assertTrue(set(required_policies(rules)) <= set(self.routing["policy_groups"]))
            self.assertNotIn("aiyun", required_policies(rules))
            self.assertNotIn("Paypal", required_policies(rules))
        self.assertIn("RULE-SET,apns,APNS", clash["rules"])
        self.assertIn("RULE-SET,netflix_domain,Netflix", clash["rules"])
        for name, policy in (("apns", "APNS"), ("netflix_domain", "Netflix"), ("github_domain", "GitHub"),
                             ("onedrive_domain", "OneDrive"), ("microsoft_domain", "Microsoft"),
                             ("paypal_domain", "PayPal")):
            self.assertTrue(any(r.endswith(f"/{name}.list,{policy}") for r in surge))

    def test_original_clash_inline_rules_are_kept(self):
        clash, surge = self.build(True)
        self.assertEqual(clash["rules"][:12], [
            "IP-CIDR,192.0.2.1/32,DIRECT,no-resolve", QUIC_RULE,
            "DOMAIN,msmp.abchina.com.cn,REJECT", "DOMAIN,api.ipify.org,Claude",
            "DOMAIN,checkip.amazonaws.com,Claude", "DOMAIN-SUFFIX,safeway.com,Claude",
            "DOMAIN,ifconfig.me,Proxy", "RULE-SET,claude_domain,Claude",
            "DOMAIN-KEYWORD,n26,N26", "DOMAIN-SUFFIX,nodeseek.com,Nodeseek",
            "DOMAIN-KEYWORD,223789,Magpie-Proxy", "DOMAIN-KEYWORD,023168,Magpie"])
        self.assertEqual(clash["rules"], [normalize_surge_rule(r, self.manifest) for r in surge if not r.startswith("SUBNET,")])

    def test_quic_uses_identical_cn_providers_not_separate_geodatabases(self):
        clash, surge = self.build()
        self.assertEqual(clash["rules"][0], QUIC_RULE)
        self.assertTrue(surge[0].startswith("AND,((PROTOCOL,UDP),(DEST-PORT,443),"))
        for name in ("cn_domain", "cn_ip"):
            self.assertIn(f"(RULE-SET,{name})", QUIC_RULE)
            self.assertIn(f"/Surge/{name}.list", surge[0])
        self.assertNotIn("GEOSITE", QUIC_RULE)
        self.assertNotIn("GEOIP", QUIC_RULE)

    def test_no_resolve_semantics_are_equal(self):
        clash, surge = self.build()
        for name, policy in (("private_ip", "DIRECT"), ("telegram_ip", "Proxy"),
                             ("netflix_ip", "Netflix"), ("apple_ip", "Apple")):
            self.assertIn(f"RULE-SET,{name},{policy},no-resolve", clash["rules"])
            self.assertTrue(any(r.endswith(f"/{name}.list,{policy},no-resolve") for r in surge))
        self.assertIn("RULE-SET,cn_ip,DIRECT", clash["rules"])
        self.assertEqual(surge_rules(["192.0.2.0/24"], "ipcidr", False), ["IP-CIDR,192.0.2.0/24"])
        self.assertEqual(surge_rules(["192.0.2.0/24"], "ipcidr"), ["IP-CIDR,192.0.2.0/24,no-resolve"])

    def test_cn_resolution_semantics_cannot_drift(self):
        next(r for r in self.manifest["rules"] if r["name"] == "cn_ip")["surge_no_resolve"] = True
        with self.assertRaisesRegex(ValueError, "CN IP DNS"):
            validate_routing(self.manifest, self.routing, self.contract)

    def test_invalid_resolution_option_rejected(self):
        for name, value in (("cn_ip", "false"), ("cn_domain", False)):
            manifest = copy.deepcopy(self.manifest)
            next(r for r in manifest["rules"] if r["name"] == name)["surge_no_resolve"] = value
            with self.assertRaises(ValueError):
                validate_manifest(manifest)

    def test_same_fallback_without_surge_only_lan_or_dns_failed(self):
        clash, surge = self.build()
        self.assertEqual(clash["rules"][-4:], FALLBACK)
        self.assertEqual(surge[-4:], ["DEST-PORT,80,Final", "DEST-PORT,443,Final",
                                     "DEST-PORT,22,Final", "FINAL,DIRECT"])
        self.assertNotIn("RULE-SET,LAN,DIRECT", surge)
        self.assertFalse(any("dns-failed" in r for r in surge))

    def test_only_two_reviewed_wifi_exceptions_and_no_removed_rules(self):
        clash, surge = self.build(True)
        self.assertFalse(any(r.startswith("SUBNET,") for r in clash["rules"]))
        wifi = [r for r in surge if r.startswith("SUBNET,")]
        self.assertEqual(len(wifi), 2)
        claude = next(r for r in surge if "/claude_domain.list?" in r)
        bank = next(r for r in surge if "/usbank.list," in r)
        self.assertEqual(surge[surge.index(claude) + 1], wifi[0])
        self.assertEqual(surge[surge.index(bank) + 1], wifi[1])
        routing = copy.deepcopy(self.routing)
        routing["surge_wifi"][0]["after"] = "ai"
        with self.assertRaisesRegex(ValueError, "reviewed Surge Wi-Fi"):
            validate_routing(self.manifest, routing, self.contract)
        for data in render_profiles(self.manifest, self.routing, self.contract).values():
            for word in (b"ruleset.skk.moe", b"usvisascheduling.com"):
                self.assertNotIn(word, data)

    def test_private_host_placeholder_present_in_both_templates(self):
        artifacts = render_profiles(self.manifest, self.routing, self.contract)
        self.assertIn(b'  # - "IP-CIDR,{{TAILSCALE_DIRECT_IPV4}}/32,DIRECT,no-resolve"',
                      artifacts["Profiles/Clash.rules.yaml"])
        self.assertIn(b"# IP-CIDR,{{TAILSCALE_DIRECT_IPV4}}/32,DIRECT,no-resolve",
                      artifacts["Profiles/Surge.rules.conf"])
        self.assertIn(b"# SUBNET,SSID:{{HOME_WIFI_SSID}},DIRECT", artifacts["Profiles/Surge.rules.conf"])
        for data in artifacts.values():
            self.assertNotIn(b"192.0.2.1", data)

    def test_claude_cannot_be_redirected(self):
        next(r for r in self.routing["common"]["routes"] if r[0] == "claude_domain")[1] = "Proxy"
        with self.assertRaisesRegex(ValueError, "Claude guards"):
            validate_routing(self.manifest, self.routing, self.contract)

    def test_apns_and_apple_cannot_be_merged(self):
        for name, policy in (("apns", "Apple"), ("apple_domain", "APNS"), ("apple_ip", "APNS")):
            routing = copy.deepcopy(self.routing)
            next(r for r in routing["common"]["routes"] if r[0] == name)[1] = policy
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "separate policy groups"):
                validate_routing(self.manifest, routing, self.contract)

    def test_all_priority_pairs_are_enforced(self):
        for first, second in self.contract["priority_overlaps"] + [["apns", "apple_domain"]]:
            routing = copy.deepcopy(self.routing)
            routes = routing["common"]["routes"]
            a, b = [next(i for i, r in enumerate(routes) if r[0] == n) for n in (first, second)]
            routes[a], routes[b] = routes[b], routes[a]
            with self.subTest(first=first), self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_missing_duplicate_dns_or_direct_node_route_rejected(self):
        for replacement in (None, ["ai", "AI"], ["fakeipfilter_domain", "DIRECT"], ["claude_domain", "aiyun"]):
            routing = copy.deepcopy(self.routing)
            routing["common"]["routes"].pop(0)
            if replacement:
                routing["common"]["routes"].insert(0, replacement)
            with self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_geographical_catchall_cannot_swallow_specific_rules(self):
        routes = self.routing["common"]["routes"]
        catchall = next(r for r in routes if r[0] == "geolocation-!cn")
        routes.remove(catchall)
        routes.insert(0, catchall)
        with self.assertRaises(ValueError):
            validate_routing(self.manifest, self.routing, self.contract)

    def test_no_extra_settings_or_unreviewed_fallback(self):
        for key, value in (("proxies", []), ("fallback", ["MATCH,Proxy"])):
            routing = copy.deepcopy(self.routing)
            routing["common"][key] = value
            with self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_private_template_removal_or_replacement_rejected(self):
        for change in ("remove", "value", "activate"):
            routing = copy.deepcopy(self.routing)
            rules = routing["common"]["insertions"][0]["rules"]
            if change == "remove":
                rules.pop(0)
            elif change == "value":
                rules[0]["template"] = "IP-CIDR,192.0.2.1/32,DIRECT,no-resolve"
            else:
                rules[0] = {"id": "tailscale-direct", "rule": "IP-CIDR,192.0.2.1/32,DIRECT,no-resolve"}
            with self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_unknown_duplicate_and_unsafe_insertions_rejected(self):
        for change in ("anchor", "duplicate", "extra", "newline", "node", "wifi"):
            routing = copy.deepcopy(self.routing)
            insertion = routing["common"]["insertions"][0]
            if change == "anchor":
                insertion["before"] = "unknown"
            elif change == "duplicate":
                insertion["rules"].append(insertion["rules"][1].copy())
            elif change == "extra":
                insertion["rules"][1]["password"] = "must-not-publish"
            elif change == "newline":
                insertion["rules"][1]["rule"] += "\n[Proxy]"
            elif change == "node":
                insertion["rules"][1]["rule"] = "DOMAIN-SUFFIX,nodeseek.com,aiyun"
            else:
                insertion["rules"][1]["rule"] = "SUBNET,SSID:private,DIRECT"
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_template_values_cannot_inject_rules(self):
        for value in ("192.0.2.1,Proxy", "bad\nFINAL,DIRECT", "999.0.0.1"):
            with self.assertRaises(ValueError):
                build_profiles(self.manifest, self.routing, self.contract, {**TEST_TEMPLATE_VALUES, "TAILSCALE_DIRECT_IPV4": value})

    def test_rendered_active_rules_exactly_match_builder(self):
        clash, surge = self.build()
        artifacts = render_profiles(self.manifest, self.routing, self.contract)
        rendered_clash = [json.loads(line[4:]) for line in artifacts["Profiles/Clash.rules.yaml"].decode().splitlines()
                          if line.startswith("  - ")]
        rendered_surge = [line for line in artifacts["Profiles/Surge.rules.conf"].decode().splitlines()
                          if line and not line.startswith(("#", "["))]
        self.assertEqual(rendered_clash, clash["rules"])
        self.assertEqual(rendered_surge, surge)

    def test_no_credentials_or_connection_sections_published(self):
        for data in render_profiles(self.manifest, self.routing, self.contract).values():
            for forbidden in (b"password:", b"uuid:", b"secret:", b"[Proxy]", b"proxies:"):
                self.assertNotIn(forbidden, data)

    def test_generation_does_not_mutate_canonical_source(self):
        before = copy.deepcopy(self.routing)
        profile_entries(self.manifest, self.routing, "surge")
        self.build(True)
        self.assertEqual(self.routing, before)


if __name__ == "__main__":
    unittest.main()
