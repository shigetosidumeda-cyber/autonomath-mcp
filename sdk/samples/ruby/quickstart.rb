# 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。
#
# 税務会計AI — Ruby quickstart
# ----------------------------------------------------------
# Run: `ruby quickstart.rb`  (Ruby 3.0+; stdlib only — Net::HTTP + JSON)
# Set ZEIMU_KAIKEI_API_KEY=sk_xxx for paid (¥3/req).
# Without a key, runs anonymous: 50 req/月 per IP.

require 'net/http'
require 'uri'
require 'json'

BASE_URL = 'https://api.zeimu-kaikei.ai/v1'
API_KEY  = ENV['ZEIMU_KAIKEI_API_KEY']

def call(path, params = {})
  uri = URI(BASE_URL + path)
  query = []
  params.each do |k, v|
    if v.is_a?(Array)
      v.each { |x| query << [k.to_s, x.to_s] }
    elsif !v.nil?
      query << [k.to_s, v.to_s]
    end
  end
  uri.query = URI.encode_www_form(query) unless query.empty?

  req = Net::HTTP::Get.new(uri)
  req['Accept'] = 'application/json'
  req['X-API-Key'] = API_KEY if API_KEY

  res = Net::HTTP.start(uri.hostname, uri.port, use_ssl: true) { |http| http.request(req) }

  case res.code.to_i
  when 401
    raise 'auth failed: check ZEIMU_KAIKEI_API_KEY'
  when 429
    raise "rate limited; retry-after=#{res['retry-after'] || '?'}s (anon = 50/月)"
  when 500..599
    raise "server error #{res.code}: try again later"
  end
  raise "HTTP #{res.code}: #{res.body}" unless res.is_a?(Net::HTTPSuccess)

  JSON.parse(res.body)
end

begin
  puts '[1] Search programs: q=省エネ tier=S,A limit=3'
  progs = call('/programs/search', q: '省エネ', tier: %w[S A], limit: 3)
  puts "    total hits: #{progs['total']}"
  progs['results'].each do |p|
    puts "    - #{p['unified_id']}  [#{p['tier']}]  #{p['primary_name']}"
  end

  puts
  puts '[2] List tax incentives (中小企業税制): limit=3'
  tax = call('/tax_rulesets/search', q: '中小企業', limit: 3)
  puts "    total hits: #{tax['total']}"
  tax['results'].each do |r|
    puts "    - #{r['unified_id']}  [#{r['ruleset_kind']}]  #{r['ruleset_name']}"
  end

  mode = API_KEY ? 'authenticated (¥3/req)' : 'anonymous (50/月 free)'
  puts
  puts "Mode: #{mode}"
rescue => e
  warn "ERROR: #{e.message}"
  exit 1
end
