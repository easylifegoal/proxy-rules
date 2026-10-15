#!/usr/bin/env ruby
# SPDX-License-Identifier: GPL-3.0-only
# Optional read-only local audit. Never copies private profiles into the repository.
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
  # Report positions, never print private values or source configuration contents.
  abort "#{client}: rule order/content differs at positions #{mismatches.map { |n| n + 1 }.join(',')}" unless mismatches.empty?
end

clash_text = File.read(options[:clash])
clash = YAML.safe_load(clash_text, aliases: true)
template_text = File.read(File.join(root, 'Profiles/Clash.rules.yaml'))
template = YAML.safe_load(template_text.gsub(/^  # - /, '  - '), aliases: true)
private_rules = clash.fetch('rules').grep(/^IP-CIDR,[0-9.]+\/32,DIRECT,no-resolve$/)
abort 'Clash: expected exactly one private Tailscale host rule' unless private_rules.size == 1
ip = private_rules.first.split(',')[1].split('/')[0]
abort 'Clash: private host is outside Tailscale address space; review required' unless IPAddr.new('100.64.0.0/10').include?(IPAddr.new(ip))
clash_rules = clash.fetch('rules').map do |rule|
  rule == private_rules.first ? 'IP-CIDR,{{TAILSCALE_DIRECT_IPV4}}/32,DIRECT,no-resolve' : rule
end
compare_rules('Clash', template.fetch('rules'), clash_rules)
abort 'Clash: provider definitions differ' unless template.fetch('rule-providers') == clash.fetch('rule-providers')

def surge_rules(text, include_templates: false)
  section = text.split(/^\[Rule\]\s*$/m, 2)[1]
  abort 'Missing Surge Rule section' unless section
  section = section.split(/^\[/, 2)[0]
  section.lines.map(&:strip).each_with_object([]) do |line, rules|
    line = line.delete_prefix('# ') if include_templates && line.start_with?('# SUBNET,')
    rules << line unless line.empty? || line.start_with?('#')
  end
end

surge = surge_rules(File.read(options[:surge]))
wifi = surge.select { |rule| rule.start_with?('SUBNET,') }
abort 'Surge: expected exactly two private Wi-Fi rules' unless wifi.size == 2 && wifi.all? { |r| r.match?(/\ASUBNET,(?:SSID:[^,"\r\n]+|"SSID:[^"\r\n]+"),DIRECT\z/) }
replacements = ['SUBNET,SSID:{{HOME_WIFI_SSID}},DIRECT', 'SUBNET,"SSID:{{COMPANY_WIFI_SSID}}",DIRECT']
normalized = surge.map { |rule| wifi.include?(rule) ? replacements[wifi.index(rule)] : rule }
surge_template = surge_rules(File.read(File.join(root, 'Profiles/Surge.rules.conf')), include_templates: true)
compare_rules('Surge', surge_template, normalized)
puts JSON.generate({clash_enabled_rules: clash_rules.size, clash_private_placeholders: 1,
                    surge_enabled_rules: surge.size, surge_private_placeholders: 2,
                    complete_ordered_match: true, provider_definitions_match: true,
                    disabled_ad_rules_excluded: true, private_profiles_modified: false})
