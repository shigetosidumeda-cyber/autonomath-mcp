// 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。
//
// jpcite — Go quickstart
// ----------------------------------------------------------
// Run: `go run quickstart.go`  (Go 1.21+; stdlib net/http only, zero deps)
// Set JPCITE_API_KEY=am_xxx to use a paid key (¥3/req).
// Without a key, runs anonymous: 3 req/日 per IP.

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
)

const baseURL = "https://api.jpcite.com/v1"

func apiKey() string {
	if key := os.Getenv("JPCITE_API_KEY"); key != "" {
		return key
	}
	return os.Getenv("AUTONOMATH_API_KEY")
}

type Program struct {
	UnifiedID   string `json:"unified_id"`
	PrimaryName string `json:"primary_name"`
	Tier        string `json:"tier"`
}

type SearchResp struct {
	Total   int       `json:"total"`
	Results []Program `json:"results"`
}

type TaxRule struct {
	UnifiedID   string `json:"unified_id"`
	RulesetName string `json:"ruleset_name"`
	RulesetKind string `json:"ruleset_kind"`
}

type TaxResp struct {
	Total   int       `json:"total"`
	Results []TaxRule `json:"results"`
}

func call(path string, params url.Values, out interface{}) error {
	u, _ := url.Parse(baseURL + path)
	u.RawQuery = params.Encode()

	req, _ := http.NewRequest("GET", u.String(), nil)
	req.Header.Set("Accept", "application/json")
	if key := apiKey(); key != "" {
		req.Header.Set("X-API-Key", key)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("transport: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	switch {
	case resp.StatusCode == 401:
		return fmt.Errorf("auth failed: check JPCITE_API_KEY")
	case resp.StatusCode == 429:
		return fmt.Errorf("rate limited; retry-after=%s (anon = 3/日)", resp.Header.Get("Retry-After"))
	case resp.StatusCode >= 500:
		return fmt.Errorf("server error %d: try again later", resp.StatusCode)
	case resp.StatusCode >= 400:
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}
	return json.Unmarshal(body, out)
}

func main() {
	fmt.Println("[1] Search programs: q=省エネ tier=S,A limit=3")
	p := url.Values{}
	p.Set("q", "省エネ")
	p.Add("tier", "S")
	p.Add("tier", "A")
	p.Set("limit", "3")
	var progs SearchResp
	if err := call("/programs/search", p, &progs); err != nil {
		fmt.Fprintln(os.Stderr, "ERROR:", err)
		os.Exit(1)
	}
	fmt.Printf("    total hits: %d\n", progs.Total)
	for _, r := range progs.Results {
		fmt.Printf("    - %s  [%s]  %s\n", r.UnifiedID, r.Tier, r.PrimaryName)
	}

	fmt.Println("\n[2] List tax incentives (中小企業税制): limit=3")
	t := url.Values{}
	t.Set("q", "中小企業")
	t.Set("limit", "3")
	var tax TaxResp
	if err := call("/tax_rulesets/search", t, &tax); err != nil {
		fmt.Fprintln(os.Stderr, "ERROR:", err)
		os.Exit(1)
	}
	fmt.Printf("    total hits: %d\n", tax.Total)
	for _, r := range tax.Results {
		fmt.Printf("    - %s  [%s]  %s\n", r.UnifiedID, r.RulesetKind, r.RulesetName)
	}

	mode := "anonymous (3/日 free)"
	if apiKey() != "" {
		mode = "authenticated (¥3/req)"
	}
	fmt.Println("\nMode:", mode)
}
