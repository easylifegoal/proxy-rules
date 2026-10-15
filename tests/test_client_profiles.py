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
        self.assertEqual(len(clash["rules"]), 26)
        self.assertEqual(len(surge), 24)
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


if __name__ == "__main__":
    unittest.main()
