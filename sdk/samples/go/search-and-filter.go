// 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。
//
// 税務会計AI — Go paginated search + filter chain
// ----------------------------------------------------------
// Run: `go run search-and-filter.go`  (Go 1.21+; stdlib only)
// Demonstrates:
//   - paginating /v1/programs/search with limit/offset
//   - filtering by prefecture + tier + funding_purpose
//   - 429 retry-after + 5xx exponential backoff

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"
)

const (
	baseURL  = "https://api.zeimu-kaikei.ai/v1"
	pageSize = 20
	maxPages = 3 // cap to spare anonymous quota (50/月)
)

type Program struct {
	UnifiedID       string  `json:"unified_id"`
	PrimaryName     string  `json:"primary_name"`
	Tier            string  `json:"tier"`
	AmountMaxManYen *float64 `json:"amount_max_man_yen"`
}

type SearchResp struct {
	Total   int       `json:"total"`
	Limit   int       `json:"limit"`
	Offset  int       `json:"offset"`
	Results []Program `json:"results"`
}

func describeStatus(code int, body string) string {
	switch {
	case code == 401:
		return "auth failed: ZEIMU_KAIKEI_API_KEY missing or invalid"
	case code == 403:
		return "forbidden: key revoked or quota exhausted"
	case code == 429:
		return "rate limited (anon = 50/月; auth = burst limit)"
	case code == 404:
		return "not found"
	case code >= 500:
		return fmt.Sprintf("server error %d: try again later", code)
	}
	return fmt.Sprintf("HTTP %d: %s", code, body)
}

func call(path string, params url.Values, attempt int) (*SearchResp, error) {
	u, _ := url.Parse(baseURL + path)
	u.RawQuery = params.Encode()

	req, _ := http.NewRequest("GET", u.String(), nil)
	req.Header.Set("Accept", "application/json")
	if key := os.Getenv("ZEIMU_KAIKEI_API_KEY"); key != "" {
		req.Header.Set("X-API-Key", key)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("transport: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode == 429 && attempt < 2 {
		retry, _ := strconv.Atoi(resp.Header.Get("Retry-After"))
		if retry == 0 {
			retry = 1
		}
		fmt.Fprintf(os.Stderr, "    retry in %ds ...\n", retry)
		time.Sleep(time.Duration(retry) * time.Second)
		return call(path, params, attempt+1)
	}
	if resp.StatusCode >= 500 && attempt < 2 {
		wait := time.Duration(500*(1<<attempt)) * time.Millisecond
		fmt.Fprintf(os.Stderr, "    server %d, backing off %v\n", resp.StatusCode, wait)
		time.Sleep(wait)
		return call(path, params, attempt+1)
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf(describeStatus(resp.StatusCode, string(body)))
	}

	var out SearchResp
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("parse: %w", err)
	}
	return &out, nil
}

func main() {
	// Filter chain: keyword + tier S/A. Broad enough that anonymous tier
	// sees pagination kick in; tighten with prefecture / funding_purpose
	// for narrower queries.
	filters := url.Values{}
	filters.Set("q", "省エネ")
	filters.Add("tier", "S")
	filters.Add("tier", "A")

	auth := "anonymous"
	if os.Getenv("ZEIMU_KAIKEI_API_KEY") != "" {
		auth = "authenticated"
	}
	fmt.Println("Filters:", filters.Encode())
	fmt.Println("API base:", baseURL)
	fmt.Println("Auth:", auth)
	fmt.Println()

	totalSeen := 0
	pageNum := 0
	for offset := 0; pageNum < maxPages; offset += pageSize {
		p := url.Values{}
		for k, v := range filters {
			p[k] = v
		}
		p.Set("limit", strconv.Itoa(pageSize))
		p.Set("offset", strconv.Itoa(offset))

		page, err := call("/programs/search", p, 0)
		if err != nil {
			fmt.Fprintln(os.Stderr, "ERROR:", err)
			os.Exit(1)
		}
		pageNum++
		fmt.Printf("--- page %d (offset=%d, total=%d) ---\n", pageNum, offset, page.Total)
		for _, prog := range page.Results {
			amt := "金額未定"
			if prog.AmountMaxManYen != nil {
				amt = fmt.Sprintf("%.0f万円", *prog.AmountMaxManYen)
			}
			name := prog.PrimaryName
			if len(name) > 50 {
				name = name[:50]
			}
			fmt.Printf("  %s [%s] %s  %s\n", prog.UnifiedID, prog.Tier, amt, name)
		}
		totalSeen += len(page.Results)
		if len(page.Results) < pageSize || offset+pageSize >= page.Total {
			break
		}
	}

	fmt.Printf("\nFetched %d programs across %d page(s).\n", totalSeen, pageNum)
	if os.Getenv("ZEIMU_KAIKEI_API_KEY") != "" {
		fmt.Printf("Cost: %d req × ¥3 = ¥%d (税抜)\n", pageNum, pageNum*3)
	}
}
