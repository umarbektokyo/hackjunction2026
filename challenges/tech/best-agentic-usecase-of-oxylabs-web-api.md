# Best agentic usecase of Oxylabs Web API

**By:** Oxylabs · **Type:** Tech challenge · **Track:** Agentic AI Track · **Tags:** AI

**Page:** https://hackjunction.app/participate/45/tech-challenges/32 · **Website:** https://oxylabs.io/

Design your project around the Oxylabs Web API: use live search and scraping to verify and inform your AI agent with what is true on the web right now.

## Introduction

AI models are brilliant but can be out of date. The moment an agent needs today's price, this morning's regulation or a page hidden behind JavaScript and bot checks, it either guesses or fails. Reliable access to the live web is essential for an agent people can trust. We are bringing our new Web API to Junction so you can build agents that know what is true right now, and can show their sources.

## The Challenge

**Challenge description:** Utilize the Oxylabs Web API in the AI agent or product you are building for your main challenge, and make it act on what is true on the web right now. Whatever problem your team tackles, live web data lets your solution check facts, track changes, compare offers and ground its answers in current, cited sources instead of stale training data. Your solution must use the Oxylabs Web API at runtime to find and read its information: search to find, scrape to read. The form is open, from a chat agent or monitoring tool to a voice assistant. Show us that it gets the answer right today and can prove where it came from.  
To submit, use the same GitHub repository and demo as your main challenge, and add a short note on which Web API endpoints you used and why.

**Inspiration:**  
Your solution may build on one of the ideas below, or you may come up with an entirely different use case depending on your choice of main challenge. Think of users whose decisions go wrong when information is stale: a shopper, a small business owner, a journalist, a compliance officer, a job seeker.

* **One market, different prices.** Compare the same product, service or offer across European countries using geo-targeted search and the commerce scrapers.  
* **Fact-checker that reads the source.** Verify a claim by reading the full pages, not the snippets, and return a verdict with citations.  
* **What does AI say about you?** Compare the answers ChatGPT, Gemini, Perplexity and Google AI Mode give on a topic with what the web says.  
* **Watchers for small teams.** Track regulations, tenders, grants or competitor pages and explain what changed and why it matters.

**Minimum requirements:**

* The demo makes at least one live Web API call (/search or /scrape) at runtime. Pre-downloaded data alone does not count.  
* The solution shows the source URLs behind what it states or decides.

## Resources

## The Technology

Oxylabs Web API is a REST API with two endpoints. /search finds the right pages on the live web, and /scrape reads any public page and returns it as Markdown, HTML, structured JSON or a screenshot. It handles JavaScript rendering, bot challenges, proxies and geo-targeting, so one HTTP call gives you clean data ready for your code or your LLM.

**Key capabilities:**

* Search the live web and get ranked results (title, snippet, URL), localised to any country  
* Read any public page as clean Markdown, sized for an LLM context window  
* Extract structured JSON from any page by describing the fields in a prompt (AI Parsing)  
* Get parsed fields from 50+ dedicated scrapers: Search, Maps, Shopping and Trends, Amazon, YouTube subtitles and metadata, eBay, Walmart and more  
* Query ChatGPT, Gemini, Perplexity and Google AI Mode and get their answers with cited sources  
* Plug it into Claude Code, Cursor or your own agent with one command, via the MCP server or agent skills

## Getting started

1. Create a free account at dashboard.oxylabs.io.  
2. Buy the Flexible plan with a price of $500. Use code JUNCTION2026 at checkout to get a full discount for the first month. **Remember to cancel your subscription once you've completed the challenge to avoid being charged monthly.**
3. Click + Add product instance, choose Web API, create it and copy the API key.  
4. Export the key in your terminal: `export OXYLABS_WEB_API_KEY=your_api_key_here`  
5. Follow the Manual or AI Agent integration here: [https\://developers.oxylabs.io/get-started/quick-start-web-api](https://developers.oxylabs.io/get-started/quick-start-web-api)

## Recommended setup

Any OS with a terminal. Python 3.10+ with requests, or Node.js 18+ (built-in fetch); there is no SDK to install. Optional: uv for the MCP server and Node.js for the agent skills. Bring your own LLM key if your agent needs a model.

**Contacts:**
Justas Kašėta (technical contact), justas.kaseta@oxylabs.io

## Judging criteria

- **Use of the Web API** (30%) – How well and how creatively it is used: search-to-scrape, AI Parsing, dedicated scrapers, geo-targeting.
- **Real-world value** (25%) – A clear user and a problem that live web data solves.
- **Trust** (20%) – Answers are current, sourced and honest about failures.
- **Execution** (15%) – It works live in front of the judges.
- **Originality** (10%) – Something we have not seen before.

## Prizes

- **The winning team:** The winning team will receive a €1,000 Apple gift voucher, plus $500 in Oxylabs product credits for each team member to use our web data collection products and explore their potential for future projects.
