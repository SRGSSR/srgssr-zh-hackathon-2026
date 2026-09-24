# Static analysis of the Utility's rendered LiteLLM config (rendered/config-<env>.yaml, produced by render.sh):
# per model group: deployments + api_base host + jurisdiction assessment, direct fallbacks (flag cross-family /
# non-CH), and the transitive reach LiteLLM can walk (fallbacks recurse, ROUTER_MAX_FALLBACKS=5).
# Usage: ruby fallback_graph.rb prod|staging
require "yaml"
env = ARGV[0] || "prod"
cfg = YAML.load(File.read(File.join(__dir__, "rendered", "config-#{env}.yaml")))

# Host assessment. "CH" only where supported; otherwise "unknown" or the best-supported non-CH value.
HOSTS = {
  "api.infomaniak.com"   => ["Infomaniak", "CH", "medium: Swiss company (Geneva); DC location per provider claim, not verified"],
  "api.featherless.ai"   => ["Featherless.ai", "unknown", "no evidence in repo; not CH-verified"],
  "api.sea-lion.ai"      => ["AI Singapore (SEA-LION API)", "SG", "medium: repo attributes SEA-LION to AI Singapore/Singapore (sponsor_attribution.py L12,L60-61); DC not verified"],
  "llmlab.plgrid.pl"     => ["PLGrid / Cyfronet AGH", "PL (EU)", "medium: .pl national grid; sponsor_attribution.py L26,L73-74 says Cyfronet AGH Cracow"],
  "api.nextbit256.com"   => ["unknown (NEXBIT_API_KEY)", "unknown", "no evidence in repo"],
  "router.huggingface.co"=> ["Hugging Face router -> Cohere (':cohere' suffix)", "non-CH (unknown DC)", "low-medium: HF router is a US-incorporated service; provider Cohere"],
  "www.example.com"      => ["placeholder (mock, fails)", "n/a", "mock-model.yaml L3 comment: used to test fallbacks"],
}
def family(g)
  case g
  when %r{^swiss-ai/apertus} then "Apertus"
  when /Qwen-SEA-LION/ then "SEA-LION(Qwen)"
  when /Gemma-SEA-LION/ then "SEA-LION(Gemma)"
  when /Bielik/ then "Bielik"
  when /ALIA/ then "ALIA"
  when /command-a/ then "Cohere Command"
  when %r{^mock/} then "mock"
  when /Cohere/ then "Cohere(Bedrock)"
  else g end
end
groups = Hash.new { |h, k| h[k] = [] }
cfg["model_list"].each do |m|
  lp = m["litellm_params"]
  host = lp["api_base"] ? lp["api_base"][%r{^https?://([^/]+)}, 1] : "bedrock:#{lp['aws_region_name']}"
  groups[m["model_name"]] << host
end
fb = {}
(cfg.dig("router_settings", "fallbacks") || []).each { |h| h.each { |k, v| fb[k] = v } }
def juris(host)
  return ["AWS Bedrock", "DE/EU region (AWS, US company)", "high for region"] if host.start_with?("bedrock:")
  HOSTS[host] || ["?", "unknown", "not in table"]
end
puts "=== #{env}: model groups (#{groups.size})"
groups.each do |g, hosts|
  hs = hosts.map { |h| j = juris(h); "#{h} [#{j[0]} | #{j[1]}]" }
  puts "#{g}  (family #{family(g)})\n    deployments: #{hs.join('; ')}"
end
puts "\n=== #{env}: direct fallbacks (flags: XF=cross-family, NONCH=target group has a deployment not assessed CH)"
fb.each do |src, tgts|
  tgts.each do |t|
    flags = []
    flags << "XF" if family(t) != family(src)
    flags << "NONCH" if (groups[t] || []).any? { |h| juris(h)[1] != "CH" }
    flags << "MISSING-GROUP" unless groups.key?(t)
    puts "#{src} -> #{t}  #{flags.join(',')}"
  end
end
puts "\n=== #{env}: transitive reach (depth<=5) and hosts that can receive a request for that group"
groups.keys.each do |g|
  seen = [g]; frontier = [g]; depth = 0
  while depth < 5 && !frontier.empty?
    nxt = []
    frontier.each { |x| (fb[x] || []).each { |t| next if seen.include?(t); seen << t; nxt << t } }
    frontier = nxt; depth += 1
  end
  hosts = seen.flat_map { |x| groups[x] || [] }.uniq
  nonch = hosts.reject { |h| juris(h)[1] == "CH" }
  puts "#{g}: reach=#{seen.drop(1).inspect}\n    hosts=#{hosts.inspect}\n    non-CH-or-unknown hosts reachable=#{nonch.inspect}"
end
