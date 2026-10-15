# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import unittest

from scripts.client_profiles import build_profiles, render_profiles, validate_routing

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
        self.assertEqual(len(clash["rules"]), 30)
        self.assertEqual(len(surge), 28)
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

    def test_claude_guards_exist_once_before_canonical_and_generic_sets(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        expected = ["DOMAIN-SUFFIX,claude-api.com,Claude",
                    "DOMAIN-SUFFIX,claudecontentmoderation.com,Claude",
                    "DOMAIN-KEYWORD,anthropic,Claude", "DOMAIN-KEYWORD,claude,Claude"]
        for rules in (clash["rules"], surge):
            for guard in expected:
                self.assertEqual(rules.count(guard), 1)
                for name in ("claude_domain", "ai", "global_media_domain", "geolocation-!cn"):
                    target = next(r for r in rules if r.startswith(f"RULE-SET,{name},")
                                  or f"/Surge/{name}.list," in r)
                    self.assertLess(rules.index(guard), rules.index(target))

    def test_claude_guards_cannot_be_removed_or_redirected_silently(self):
        for index in range(4):
            routing = json.loads(json.dumps(self.routing))
            routing["claude_guards"].pop(index)
            with self.assertRaisesRegex(ValueError, "Claude guard"):
                validate_routing(self.manifest, routing, self.contract)
        for client in ("clash", "surge"):
            routing = json.loads(json.dumps(self.routing))
            next(r for r in routing[client]["routes"] if r[0] == "claude_domain")[1] = "Proxy"
            with self.assertRaisesRegex(ValueError, "Claude guards"):
                validate_routing(self.manifest, routing, self.contract)

    def test_claude_keyword_matching_is_intentionally_broad(self):
        clash, surge = build_profiles(self.manifest, self.routing, self.contract)
        for rules in (clash["rules"], surge):
            guards = [r.split(",") for r in rules if r.startswith("DOMAIN-KEYWORD,")]
            for domain in ("api.claude-api.com", "claudecontentmoderation.com",
                           "thirdparty-claude.example", "anthropic-proxy.example"):
                self.assertTrue(any(word in domain and policy == "Claude" for _, word, policy in guards))
            self.assertFalse(any(word in "unrelated.example" for _, word, _ in guards))

    def test_keywords_are_profile_rules_not_mrs_provider_content(self):
        clash, _ = build_profiles(self.manifest, self.routing, self.contract)
        self.assertEqual(clash["rule-providers"]["claude_domain"]["behavior"], "domain")
        self.assertEqual(clash["rule-providers"]["claude_domain"]["format"], "mrs")
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
            for forbidden in (b"password:", b"uuid:", b"secret:", b"SSID:", b"[Proxy]", b"proxies:"):
                self.assertNotIn(forbidden, data)

    def test_surge_home_wifi_insertion_point_is_after_complete_claude_group(self):
        surge = render_profiles(self.manifest, self.routing, self.contract)["Profiles/Surge.rules.conf"].decode()
        marker = "# Insert local home Wi-Fi DIRECT exceptions here, AFTER all Claude rules."
        self.assertEqual(surge.count(marker), 1)
        for guard in self.routing["claude_guards"]:
            self.assertLess(surge.index(guard + ",Claude"), surge.index(marker))
        self.assertLess(surge.index("/Surge/claude_domain.list,Claude"), surge.index(marker))
        self.assertLess(surge.index(marker), surge.index("/Surge/paypal_domain.list,Paypal"))


if __name__ == "__main__":
    unittest.main()
