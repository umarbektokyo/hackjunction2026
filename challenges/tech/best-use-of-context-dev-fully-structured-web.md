# Best Use of Context.dev: Fully Structured Web

**By:** Context.dev · **Type:** Tech challenge · **Track:** Data Track · **Tags:** AI

**Page:** https://hackjunction.app/participate/45/tech-challenges/44

Plug the Context.dev API into whatever you're building and give it the live web: pages, brands, companies, people and news as clean structured data in one API call.

## The Challenge

Whatever you're building, use the **Context.dev API** to extract exactly what you need from the web and nothing more.

Live web data lets your project check facts against current sources, react when a page or news story changes, brand itself from a customer's email, or enrich a company or person in one call instead of relying on stale data.

To count, your project must call **at least one Context.dev endpoint in its core flow**, not just as a side feature.

### Minimum requirements

- Use **at least one Context.dev API endpoint** in the submitted project.
- The data from Context.dev must **visibly drive something in the demo**.

### What to submit

Submit a **GitHub repository and a demo of your project**, plus a short note on **which Context.dev endpoints you used and why**.

## Resources

## What we'll bring

Every team gets **50,000 Context.dev API credits that don't expire**, plus documentation, SDKs, an MCP server, live example projects and **Context.dev engineers on site** to help.

**No credit card needed.** There is no rate limit, with a maximum of **50 concurrent requests per organisation**. No special hardware is needed; the live web is your dataset.

## The Technology

Context.dev is a **web data API**. You send it a URL, a domain, a company or a search query, and it returns clean, structured data — markdown, JSON, screenshots, logos, colours, company facts and news — that your app or model can use right away. No scrapers, proxies or parsers to maintain.

**Key capabilities:**

- **Search and scrape:** turn pages into markdown, HTML, screenshots or images, or crawl and map a whole site.
- **Structured extraction:** extract JSON with your own schema, or get researched answers to a question.
- **Brand data:** get logos, colours, fonts and a style guide from a domain or email.
- **Search and enrichment:** search and enrich companies, people and news.
- **Monitors and webhooks:** react when a page or topic changes.
- **Batch processing:** process thousands of URLs.
- **File parsing:** parse PDFs and documents.
- **Social media:** scrape feeds such as TikTok and Instagram.

## Getting started

1. **Create an account** at [context.dev/signup](https://context.dev/signup). Coding agents can use [context.dev/auth.md](https://context.dev/auth.md).
2. **Redeem code `JUNCTION26`** at [Redeem credits](https://context.dev/dashboard/redeem-credits) to receive **50,000 API credits per team, with no expiry**.
3. **Copy a secret key** from the [API keys page](https://context.dev/dashboard/api-keys).
4. **Install the SDK:** `npm install context.dev` or `pip install context.dev`.
5. **Scrape your first page** using the code in the [Quickstart](https://docs.context.dev/quickstart). You should see the Junction homepage printed as Markdown. Swap in any URL, or try brand, search, news or monitors. Start building!

**Using a coding agent?** Point it at the [Agent quickstart](https://docs.context.dev/agent-quickstart), or connect the MCP server at [https://mcp.context.dev/mcp](https://mcp.context.dev/mcp) ([setup guide](https://docs.context.dev/install-mcp)).

**Example requests and responses:**

- **Scrape the Junction website to Markdown:** [request + response](https://gist.github.com/contextualbeer/c602446780d9270a4d817a4a677c6317).
- **Extract this event's details as JSON:** [request + response](https://gist.github.com/contextualbeer/d2a016dcd6c535e4eeffa4d6988bd403).

## Recommended setup

Use **any language over HTTP**. SDKs are available for **TypeScript/Node, Python, Ruby and Go**. If you can call an API, you can use Context.dev, whether you're building a web app, backend or something else that can make an HTTP request.

Bring any laptop with **Node.js 20+ or Python 3.9+** (Ruby 3.2+ and Go 1.22+ are also supported), or just curl. **Internet access is required.**

Optional tools: the [context-dev CLI](https://docs.context.dev/install-cli), the [agent skill](https://docs.context.dev/install-skill), or the [MCP server](https://docs.context.dev/install-mcp). To try requests without code, use the [Playground](https://www.context.dev/playground/scrape).

## Tips and common pitfalls

- **Check each output's `success` flag.** A 200 response can still contain a failed output.
- **Set `maxAgeMs: 0` when you need fresh data.** Results are cached for up to 3 days by default, and cached results cost the same credits as fresh ones. Store results in your own app to avoid paying for repeat calls.
- **Crawls, batches and monitors are asynchronous.** Poll the job or receive a webhook; use a service such as Cloudflare Tunnel for local webhooks.
- **Some sites block automated access.** Teams are responsible for respecting the terms of the sites they use.

## Documentation and examples

- **Documentation:** [docs.context.dev](https://docs.context.dev)
- **Guides:** [Quickstart](https://docs.context.dev/quickstart), [Agent quickstart](https://docs.context.dev/agent-quickstart), [Recipes](https://docs.context.dev/use-cases/live-web-context-for-agents)
- **API reference:** [Web scraping API](https://docs.context.dev/api-reference/web-scraping/scrape)
- **Operation costs:** [Credits and pricing](https://docs.context.dev/account/credits)
- **Live examples:** [GPU rental price tracker](https://gpu.context.dev) ([source](https://github.com/context-dot-dev/gpu-terminal)) and [Yapper leaderboard](https://yappers.context.dev)
- **SDKs and integrations:** [github.com/context-dot-dev](https://github.com/context-dot-dev)

There is no starter repository; start with the **Quickstart guide**.

## Mentors and support

Context.dev engineers will help with **web data extraction, search, LLM apps and large-scale data pipelines**:

- **Beer van der Drift** — CTO, challenge lead and lead judge
- **Yahia Bakour** — Founder & CEO
- **Thomas Oomens** — Engineer

**On-site availability:**

- **Friday:** until 23:00
- **Saturday:** from 09:00 until Sunday 02:00
- **Sunday:** from 07:00 until the end

Come visit the **Context.dev booth**. Main and technical contact: **Beer van der Drift**, CTO, **beer@context.dev**. Service status: [status.context.dev](https://status.context.dev).

## Judging criteria

- **Creative use of Context.dev** (40%) – Unusual sources, combining several endpoints.
- **How central live web data is to the product** (30%)
- **Technical execution** (30%) – Accuracy, latency, handling of change over time.

## Prizes

- **1st Place:** €750 + swag
- **2nd Place:** €250 + swag
- **3rd Place:** Swag
