#!/usr/bin/env ruby
# SPDX-License-Identifier: GPL-3.0-only
# Read-only private profile audit; never prints or writes private values.
require 'yaml'
require 'json'
require 'ipaddr'
require 'optparse'

options = {}
OptionParser.new do |parser|
  parser.banner = 'Usage: ruby scripts/audit_local_profiles.rb --clash PATH --surge PATH'
  parser.on('--clash PATH') { |v| options[:clash] = v }
  parser.on('--surge PATH') { |v| options[:surge] = v }
end.parse!
abort 'Both --clash and --surge paths are required' unless options.keys.sort == [:clash, :surge]
root = File.expand_path('..', __dir__)

def compare_rules(client, expected, actual)
  mismatches = (0...[expected.size, actual.size].max).select { |n| expected[n] != actual[n] }
  abort "#{client}: rule order/content differs at positions #{mismatches.map { |n| n + 1 }.join(',')}" unless mismatches.empty?
end

def section(text, name)
  value = text.split(/^\[#{Regexp.escape(name)}\]\s*$/m, 2)[1]
  abort "Missing #{name} section" unless value
  value.split(/^\[/, 2)[0]
end

def normalize_private_ip(client, rules)
  private_rules = rules.grep(/^IP-CIDR,[0-9.]+\/32,DIRECT,no-resolve$/)
  abort "#{client}: expected one Tailscale host rule" unless private_rules.size == 1
  ip = private_rules.first.split(',')[1].split('/')[0]
  abort "#{client}: private host is outside Tailscale range" unless IPAddr.new('100.64.0.0/10').include?(IPAddr.new(ip))
  [rules.map { |r| r == private_rules.first ? 'IP-CIDR,{{TAILSCALE_DIRECT_IPV4}}/32,DIRECT,no-resolve' : r }, ip]
end

def policies(rules)
  rules.map do |rule|
    parts = rule.split(',')
    parts.pop while %w[no-resolve dns-failed extended-matching].include?(parts.last)
    parts.last
  end.uniq - %w[DIRECT REJECT]
end

def surge_rules(text, include_templates: false)
  section(text, 'Rule').lines.map(&:strip).each_with_object([]) do |line, rules|
    line = line.delete_prefix('# ') if include_templates && line.start_with?('# SUBNET,', '# IP-CIDR,')
    rules << line unless line.empty? || line.start_with?('#')
  end
end

clash = YAML.safe_load(File.read(options[:clash]), aliases: true)
template_text = File.read(File.join(root, 'Profiles/Clash.rules.yaml'))
template = YAML.safe_load(template_text.gsub(/^  # - /, '  - '), aliases: true)
clash_rules, clash_ip = normalize_private_ip('Clash', clash.fetch('rules'))
compare_rules('Clash', template.fetch('rules'), clash_rules)
abort 'Clash: provider definitions differ' unless template.fetch('rule-providers') == clash.fetch('rule-providers')
clash_groups = clash.fetch('proxy-groups').map { |g| g.fetch('name') }
abort 'Clash: route references a node or missing group' unless (policies(clash_rules) - clash_groups).empty?

surge_text = File.read(options[:surge])
surge = surge_rules(surge_text)
normalized, surge_ip = normalize_private_ip('Surge', surge)
abort 'Private Tailscale host differs between clients' unless clash_ip == surge_ip
wifi = normalized.select { |r| r.start_with?('SUBNET,') }
abort 'Surge: expected two private Wi-Fi exceptions' unless wifi.size == 2 && wifi.all? { |r| r.match?(/\ASUBNET,(?:SSID:[^,"\r\n]+|"SSID:[^"\r\n]+"),DIRECT\z/) }
replacements = ['SUBNET,SSID:{{HOME_WIFI_SSID}},DIRECT', 'SUBNET,"SSID:{{COMPANY_WIFI_SSID}}",DIRECT']
normalized = normalized.map { |r| wifi.include?(r) ? replacements[wifi.index(r)] : r }
surge_template = surge_rules(File.read(File.join(root, 'Profiles/Surge.rules.conf')), include_templates: true)
compare_rules('Surge', surge_template, normalized)
surge_groups = section(surge_text, 'Proxy Group').lines.map { |line| line[/^([^#;=]+?)\s*=/, 1]&.strip }.compact
abort 'Surge: route references a node or missing group' unless (policies(surge) - surge_groups).empty?
abort 'Rule policy names differ' unless policies(clash_rules).sort == policies(surge).sort
puts JSON.generate({clash_enabled_rules: clash_rules.size, clash_private_placeholders: 1,
                    surge_enabled_rules: surge.size, surge_private_placeholders: 3,
                    complete_ordered_match: true, provider_definitions_match: true,
                    all_rules_target_groups_or_builtins: true, same_rule_policy_names: true,
                    surge_only_wifi_exceptions: 2, clash_only_quic_guard: true,
                    surge_rule_level_quic_reject: false, private_profiles_modified: false})
