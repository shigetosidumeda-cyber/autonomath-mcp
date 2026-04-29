<?php
// 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。
//
// 税務会計AI — PHP quickstart
// ----------------------------------------------------------
// Run: `php quickstart.php`  (PHP 8.0+; cURL extension only, zero composer deps)
// Set ZEIMU_KAIKEI_API_KEY=sk_xxx for paid (¥3/req).
// Without a key, runs anonymous: 50 req/月 per IP.

const BASE_URL = 'https://api.zeimu-kaikei.ai/v1';
$API_KEY = getenv('ZEIMU_KAIKEI_API_KEY') ?: null;

function call(string $path, array $params = []): array {
    global $API_KEY;

    // Build query with repeated keys for arrays (PHP defaults to brackets, which the API doesn't expect)
    $pairs = [];
    foreach ($params as $k => $v) {
        if (is_array($v)) {
            foreach ($v as $x) $pairs[] = urlencode($k) . '=' . urlencode((string)$x);
        } elseif ($v !== null) {
            $pairs[] = urlencode($k) . '=' . urlencode((string)$v);
        }
    }
    $url = BASE_URL . $path . ($pairs ? '?' . implode('&', $pairs) : '');

    $headers = ['Accept: application/json'];
    if ($API_KEY) $headers[] = 'X-API-Key: ' . $API_KEY;

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => $headers,
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_HEADER         => true,
    ]);
    $response = curl_exec($ch);
    if ($response === false) {
        $err = curl_error($ch);
        curl_close($ch);
        throw new RuntimeException("transport: $err");
    }
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $hsize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    $rawHeaders = substr($response, 0, $hsize);
    $body = substr($response, $hsize);
    curl_close($ch);

    if ($code === 401) throw new RuntimeException('auth failed: check ZEIMU_KAIKEI_API_KEY');
    if ($code === 429) {
        preg_match('/^retry-after:\s*(\d+)/im', $rawHeaders, $m);
        $retry = $m[1] ?? '?';
        throw new RuntimeException("rate limited; retry-after={$retry}s (anon = 50/月)");
    }
    if ($code >= 500) throw new RuntimeException("server error $code: try again later");
    if ($code >= 400) throw new RuntimeException("HTTP $code: $body");

    $data = json_decode($body, true);
    if ($data === null) throw new RuntimeException('invalid JSON in response');
    return $data;
}

try {
    echo "[1] Search programs: q=省エネ tier=S,A limit=3\n";
    $progs = call('/programs/search', ['q' => '省エネ', 'tier' => ['S', 'A'], 'limit' => 3]);
    echo "    total hits: {$progs['total']}\n";
    foreach ($progs['results'] as $p) {
        echo "    - {$p['unified_id']}  [{$p['tier']}]  {$p['primary_name']}\n";
    }

    echo "\n[2] List tax incentives (中小企業税制): limit=3\n";
    $tax = call('/tax_rulesets/search', ['q' => '中小企業', 'limit' => 3]);
    echo "    total hits: {$tax['total']}\n";
    foreach ($tax['results'] as $r) {
        echo "    - {$r['unified_id']}  [{$r['ruleset_kind']}]  {$r['ruleset_name']}\n";
    }

    $mode = $API_KEY ? 'authenticated (¥3/req)' : 'anonymous (50/月 free)';
    echo "\nMode: $mode\n";
} catch (Throwable $e) {
    fwrite(STDERR, 'ERROR: ' . $e->getMessage() . "\n");
    exit(1);
}
