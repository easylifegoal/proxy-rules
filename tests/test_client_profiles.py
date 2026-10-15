# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import unittest

from scripts.client_profiles import (TEST_TEMPLATE_VALUES, build_profiles,
                                     render_profiles, required_policies, validate_routing)

ROOT = Path(__file__).resolve().parents[1]


class ClientProfileTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "sources.json").read_text())
        self.routing = json.loads((ROOT / "custom/client-routing.json").read_text())
        self.contract = json.loads((ROOT / "custom/classification.json").read_text())

    def test_complete_public_profiles_have_no_private_settings(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        self.assertEqual(set(clash), {"rules", "rule-providers"})
        self.assertEqual(len(clash["rule-providers"]), 23)
        self.assertEqual(len(clash["rules"]), 36)
        self.assertEqual(len(surge), 31)
        for provider in clash["rule-providers"].values():
            self.assertTrue(provider["url"].startswith(
                "https://raw.githubusercontent.com/easylifegoal/proxy-rules/main/Clash/"))
            self.assertTrue(provider["path"].startswith("./providers/proxy-rules/"))

    def test_native_format_and_bank_output_alias(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        self.assertEqual(clash["rule-providers"]["apns"]["format"], "yaml")
        self.assertEqual(clash["rule-providers"]["apns"]["behavior"], "classical")
        self.assertTrue(clash["rule-providers"]["usbank_domain"]["url"].endswith("/usbank.mrs"))
        self.assertTrue(any("/usbank.list,USBank" in r for r in surge))
        self.assertFalse(any("fakeipfilter" in r for r in surge + clash["rules"]))

    def test_client_policy_and_fallback_differences_are_preserved(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        self.assertIn("RULE-SET,apns,Apple", clash["rules"])
        self.assertIn("RULE-SET,netflix_domain,Netflix", clash["rules"])
        self.assertIn("RULE-SET,paypal_domain,PayPal", clash["rules"])
        self.assertTrue(any(r.endswith("/paypal_domain.list,Paypal") for r in surge))
        self.assertTrue(any(r.endswith("/apns.list,APNS") for r in surge))
        self.assertTrue(any(r.endswith("/netflix_domain.list,GlobalMedia") for r in surge))
        self.assertEqual(clash["rules"][-1], "MATCH,DIRECT")
        self.assertEqual(surge[-1], "FINAL,Proxy,dns-failed")

    def test_no_resolve_semantics(self):
        clash, _ = build_profiles(self.manifest, self.routing, self.contract)
        self.assertIn("RULE-SET,private_ip,DIRECT,no-resolve", clash["rules"])
        self.assertIn("RULE-SET,cn_ip,DIRECT", clash["rules"])

    def test_merged_claude_set_precedes_generic_sets_without_inline_duplicates(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        for rules in (clash["rules"], surge):
            claude = next(r for r in rules if r.startswith("RULE-SET,claude_domain,")
                          or "/Surge/claude_domain.list?" in r)
            self.assertEqual(rules.count(claude), 1)
            self.assertFalse(any(r.startswith(("DOMAIN-SUFFIX,claude", "DOMAIN-KEYWORD,claude,",
                                              "DOMAIN-KEYWORD,anthropic,")) for r in rules))
            for name in ("ai", "global_media_domain", "geolocation-!cn"):
                target = next(r for r in rules if r.startswith(f"RULE-SET,{name},")
                              or f"/Surge/{name}.list," in r)
                self.assertLess(rules.index(claude), rules.index(target))

    def test_claude_set_cannot_be_redirected_silently(self):
        for client in ("clash", "surge"):
            routing = json.loads(json.dumps(self.routing))
            next(r for r in routing[client]["routes"] if r[0] == "claude_domain")[1] = "Proxy"
            with self.assertRaisesRegex(ValueError, "Claude guards"):
                validate_routing(self.manifest, routing, self.contract)

    def test_claude_urls_bypass_old_domain_only_cache(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        self.assertTrue(clash["rule-providers"]["claude_domain"]["url"].endswith("/claude_domain.yaml?v=classical-v1"))
        self.assertTrue(clash["rule-providers"]["claude_domain"]["path"].endswith("/claude_domain.yaml"))
        self.assertTrue(any("/claude_domain.list?v=classical-v1,Claude" in r for r in surge))

    def test_claude_uses_classical_yaml_not_partial_mrs(self):
        clash, _ = build_profiles(self.manifest, self.routing, self.contract)
        self.assertEqual(clash["rule-providers"]["claude_domain"]["behavior"], "classical")
        self.assertEqual(clash["rule-providers"]["claude_domain"]["format"], "yaml")
        self.assertEqual(len(clash["rule-providers"]), 23)

    def test_all_priority_pairs_are_enforced_in_both_clients(self):
        for client in ("clash", "surge"):
            for first, second in self.contract["priority_overlaps"] + [["apns", "apple_domain"]]:
                with self.subTest(client=client, first=first, second=second):
                    routing = json.loads(json.dumps(self.routing))
                    routes = routing[client]["routes"]
                    a, b = [next(i for i, r in enumerate(routes) if r[0] == n) for n in (first, second)]
                    routes[a], routes[b] = routes[b], routes[a]
                    with self.assertRaises(ValueError):
                        validate_routing(self.manifest, routing, self.contract)

    def test_missing_duplicate_or_dns_routing_rejected(self):
        for replacement in (None, ["ai", "AI"], ["fakeipfilter_domain", "DIRECT"]):
            routing = json.loads(json.dumps(self.routing))
            routing["clash"]["routes"].pop(0)
            if replacement:
                routing["clash"]["routes"].insert(0, replacement)
            with self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_no_extra_settings_or_unreviewed_fallback(self):
        for key, value in (("proxies", []), ("fallback", ["MATCH,Proxy"])):
            routing = json.loads(json.dumps(self.routing))
            routing["clash"][key] = value
            with self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_geographical_catchall_cannot_swallow_specific_rules(self):
        routes = self.routing["surge"]["routes"]
        catchall = next(r for r in routes if r[0] == "geolocation-!cn")
        routes.remove(catchall)
        routes.insert(0, catchall)
        with self.assertRaises(ValueError):
            validate_routing(self.manifest, self.routing, self.contract)

    def test_rendered_outputs_have_only_public_rules(self):
        artifacts = render_profiles(self.manifest, self.routing, self.contract)
        self.assertEqual(set(artifacts), {"Profiles/Clash.rules.yaml", "Profiles/Surge.rules.conf"})
        for data in artifacts.values():
            for forbidden in (b"password:", b"uuid:", b"secret:", b"[Proxy]", b"proxies:", b"ruleset.skk.moe"):
                self.assertNotIn(forbidden, data)

    def test_surge_home_wifi_insertion_point_is_after_complete_claude_group(self):
        surge = render_profiles(self.manifest, self.routing, self.contract)["Profiles/Surge.rules.conf"].decode()
        marker = "# SUBNET,SSID:{{HOME_WIFI_SSID}},DIRECT"
        self.assertEqual(surge.count(marker), 1)
        self.assertLess(surge.index("/Surge/claude_domain.list?v=classical-v1,Claude"), surge.index(marker))
        self.assertLess(surge.index(marker), surge.index("/Surge/paypal_domain.list,Paypal"))

    def test_every_enabled_rule_is_present_in_original_order(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract, TEST_TEMPLATE_VALUES)
        self.assertEqual((len(clash["rules"]), len(surge)), (37, 33))
        self.assertEqual(clash["rules"][:12], [
            "IP-CIDR,192.0.2.1/32,DIRECT,no-resolve",
            "AND,((NETWORK,UDP),(DST-PORT,443),(NOT,((OR,((GEOSITE,cn),(GEOIP,CN)))))),REJECT",
            "DOMAIN,msmp.abchina.com.cn,REJECT",
            "DOMAIN,api.ipify.org,Claude", "DOMAIN,checkip.amazonaws.com,Claude",
            "DOMAIN-SUFFIX,safeway.com,Claude", "DOMAIN,ifconfig.me,Proxy",
            "RULE-SET,claude_domain,Claude", "DOMAIN-KEYWORD,n26,N26",
            "DOMAIN-SUFFIX,nodeseek.com,Nodeseek", "DOMAIN-KEYWORD,223789,Magpie-Proxy",
            "DOMAIN-KEYWORD,023168,Magpie"])
        self.assertEqual(surge[3:11], [
            "SUBNET,SSID:EXAMPLE-HOME-WIFI,DIRECT", "DOMAIN-SUFFIX,nodeseek.com,aiyun",
            "DOMAIN,msmp.abchina.com.cn,REJECT", "DOMAIN,api.ipify.org,Claude",
            "DOMAIN,checkip.amazonaws.com,Claude", "DOMAIN-SUFFIX,safeway.com,Claude",
            "DOMAIN,ifconfig.me,Proxy", "DOMAIN-KEYWORD,n26,DIRECT"])
        self.assertEqual(surge[13], 'SUBNET,"SSID:EXAMPLE-COMPANY-WIFI",DIRECT')
        self.assertTrue(surge[12].endswith('/ai.list,AI'))
        self.assertTrue(surge[14].endswith('/private_ip.list,DIRECT'))
        self.assertFalse(any('usvisascheduling.com' in r or 'ruleset.skk.moe' in r
                             for r in clash['rules'] + surge))

    def test_private_rules_are_kept_as_commented_placeholders(self):
        profiles = render_profiles(self.manifest, self.routing, self.contract)
        clash = profiles['Profiles/Clash.rules.yaml'].decode()
        surge = profiles['Profiles/Surge.rules.conf'].decode()
        self.assertIn('  # - "IP-CIDR,{{TAILSCALE_DIRECT_IPV4}}/32,DIRECT,no-resolve"', clash)
        self.assertIn('# SUBNET,SSID:{{HOME_WIFI_SSID}},DIRECT', surge)
        self.assertIn('# SUBNET,"SSID:{{COMPANY_WIFI_SSID}}",DIRECT', surge)
        for text in (clash, surge):
            self.assertNotIn('192.0.2.1', text)
            self.assertNotIn('EXAMPLE-HOME-WIFI', text)

    def test_native_test_policies_cover_inline_routes_too(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        self.assertTrue({'N26', 'Nodeseek', 'Magpie', 'Magpie-Proxy'} <= set(required_policies(clash['rules'])))
        self.assertIn('aiyun', required_policies(surge))
        for rules in (clash['rules'], surge):
            self.assertNotIn('DIRECT', required_policies(rules))
            self.assertNotIn('REJECT', required_policies(rules))

    def test_private_template_removal_or_replacement_rejected(self):
        for client in ('clash', 'surge'):
            for change in ('remove', 'value', 'activate'):
                routing = json.loads(json.dumps(self.routing))
                rules = routing[client]['insertions'][0]['rules']
                if change == 'remove':
                    rules.pop(0)
                elif change == 'value':
                    rules[0]['template'] = 'SUBNET,SSID:actual-private-wifi,DIRECT'
                else:
                    rules[0] = {'id': rules[0]['id'], 'rule': 'IP-CIDR,192.0.2.1/32,DIRECT,no-resolve'}
                with self.subTest(client=client, change=change), self.assertRaises(ValueError):
                    validate_routing(self.manifest, routing, self.contract)

    def test_unknown_duplicate_and_unsafe_insertions_rejected(self):
        for change in ('anchor', 'duplicate', 'extra', 'newline', 'optional-ad'):
            routing = json.loads(json.dumps(self.routing))
            insertion = routing['surge']['insertions'][0]
            if change == 'anchor':
                insertion['before'] = 'unknown'
            elif change == 'duplicate':
                insertion['rules'].append(insertion['rules'][1].copy())
            elif change == 'extra':
                insertion['rules'][1]['password'] = 'must-not-publish'
            elif change == 'newline':
                insertion['rules'][1]['rule'] += '\n[Proxy]'
            else:
                insertion['rules'][1] = {'id': 'optional-ad', 'disabled': 'DOMAIN-SET,https://example.com,REJECT'}
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_routing(self.manifest, routing, self.contract)

    def test_wifi_cannot_be_moved_before_claude(self):
        self.routing['surge']['insertions'][0]['before'] = 'claude_domain'
        with self.assertRaisesRegex(ValueError, 'Claude must precede Wi-Fi'):
            validate_routing(self.manifest, self.routing, self.contract)

    def test_template_values_cannot_inject_rules(self):
        for value in ('injected,Proxy', 'bad\nFINAL,DIRECT', 'bad"quote'):
            values = {**TEST_TEMPLATE_VALUES, 'HOME_WIFI_SSID': value}
            with self.assertRaises(ValueError):
                build_profiles(self.manifest, self.routing, self.contract, values)

    def test_rendered_active_rules_exactly_match_builder_order(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        artifacts = render_profiles(self.manifest, self.routing, self.contract)
        rendered_clash = [json.loads(line[4:]) for line in
                          artifacts['Profiles/Clash.rules.yaml'].decode().splitlines()
                          if line.startswith('  - ')]
        rendered_surge = [line for line in artifacts['Profiles/Surge.rules.conf'].decode().splitlines()
                          if line and not line.startswith(('#', '['))]
        self.assertEqual(rendered_clash, clash['rules'])
        self.assertEqual(rendered_surge, surge)


if __name__ == "__main__":
    unittest.main()
