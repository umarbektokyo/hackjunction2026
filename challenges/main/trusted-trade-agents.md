# Trusted Trade Agents

**By:** Valio Aimo · **Type:** Main challenge · **Track:** Agentic AI Track · **Tags:** AI

**Page:** https://hackjunction.app/participate/45/challenges/327 · **Website:** https://www.valioaimo.fi/

How can a food-service wholesaler let autonomous purchasing agents place an order – finding products, comparing offers and getting the right approval in a fraction of the time it takes today – without exposing real systems, confidential data or the marketplace roadmap?

## Introduction
Valio Aimo® serves 20,000+ professional kitchens and is planning to build a digital B2B marketplace connecting foodservice buyers and suppliers. As ordering shifts from people clicking through a catalog to **AI agents making autonomous purchasing decisions**, the question of how a wholesaler exposes itself to those agents – what they can see, decide and be trusted with – becomes existential for data ownership, trust, and who owns the customer relationship.

The Digital B2B Marketplace is a future step in this direction; for Junction 2026 we are mocking today's webshop and backend systems, not the marketplace itself. We want you to prototype the **interface and operating model** that would let an external purchasing agent interact with Valio Aimo's systems, built on **open, verifiable standards** rather than a single platform's black box.

## The challenge
B2B ordering in foodservice and wholesale is still largely manual or menu-driven: a buyer logs into today's Valio Aimo webshop and searches a catalog. The step we want to explore is **external purchasing agents** that find, compare, order and handle exceptions on the buyer's behalf, working with Valio Aimo directly – not by building a whole marketplace, but by defining the interface and operating model through which an external agent could interact with Valio Aimo's systems at all.

### Core – your solution must enable
- **Product, price & availability lookup:** a structured way for an external agent to search for and retrieve what's available and at what price.
- **Requesting price & availability, then placing an order:** a defined interaction for moving from inquiry to commitment, based on fixed prices rather than a negotiated quote.
- **Permission & human-approval management:** what the agent may decide on its own, and what must go to a human for sign-off.

### Optional – open directions (not required to win)
- **Delivery time & sustainability comparison:** not just price, but delivery reliability and the certificates/sustainability labels already shown in the webshop. *(Category-level carbon-footprint ranges are a stretch goal.)*
- **Substitution and other exception handling:** what happens when the exact request can't be met. *(Last year's Zero-Fail Logistics challenge covered failed deliveries in depth, so this isn't scored as core.)*
- **Traceability and explainability:** a human-readable record of what the agent did and why.

### Example request
> *"I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability."*

A hotel chain's agent sends this request. Your solution returns products, prices and availability in structured form; the agent places the order within its authority or sends it to a human for approval.

**Impact:** This is not about replacing today's e-commerce UI with a chatbot. It is about defining how a European food-service wholesaler can be safely and openly readable by autonomous agents – before that interface gets defined by someone else's platform.

# Valio Aimo®

Valio Aimo® was created in 2021 as a bold leap forward by Valio, transforming traditional wholesale into a next-generation foodservice powerhouse.

We are more than a distributor: Aimo is where the breadth and agility of wholesale meet the deep product expertise, R&D capability, and brand-building strength of a global food innovator.

- **20,000 professional customers** across restaurants, foodservice operators, and industrial customers rely on us to keep their business running every single day.
- **25,000 product names** sourced from **700 trusted suppliers**, forming one of the most comprehensive foodservice assortments in Finland.
- **350 specialists** are committed to delivering excellence in logistics, service, and digital transformation.
- **Part of Valio**, Finland's leading dairy and food company, with:
  - **€2.4B in revenue**
  - Operations in **60 export markets**
  - A pioneering sustainability mission: **carbon-neutral milk by 2035**

As part of Valio, Aimo represents the cutting edge of how foodservice can be reinvented for the AI-driven age.

**Valio Aimo® is not just serving today's kitchens; we are shaping the future of foodservice.**

## Resources

## What we'll bring
- **Synthetic product catalog, simulated suppliers and mock APIs** mimicking Valio Aimo's webshop/backend systems, built on realistic data: prices, availability behaviour, delivery lead times, and sustainability certificates/labels (category-level carbon-footprint ranges as a stretch goal).
- **No real-time, live or confidential data or systems** – everything you build against is synthetic.
- **Mentoring** on AI agents, wholesale trading rules, exception handling and data governance, plus coaching on which background data and rules are essential.

**Preferred tech:** AI agents (agentic/tool-use frameworks), open data/interop standards, recommendation logic, optional verifiable-credential or trust-layer approaches. Agentic payment standards (e.g. x402, Nevermined) are relevant context but not required.

## Mentors
- **Marketplace/Commercial:** Hanna Forsström, Pirjo Kaartinen
- **Online Sales:** Minni Ruhtinas
- **IT/Tech integrations & Data governance:** Tommi Nurmi-Aro, Ville Takanen, Riku Tapper


**Access the challenge resources here:**  
https://junction26.valioaimo.fi/

**Resource portal password:** `$VALIO_AIMO_PORTAL_PASSWORD`

The resource portal contains downloadable datasets, API documentation and instructions for accessing the mock backend systems.

**API authentication:**

API key: `$VALIO_AIMO_API_KEY`

Use this API key to authenticate requests to Valio Aimo's mock APIs. Refer to the documentation in the resource portal for integration instructions.

**Webshop test accounts:** Test credentials and access instructions will be shared separately once available.

All provided data is synthetic. No production systems or confidential business data are involved.

## Judging criteria

- **Working end-to-end demo** (30%) – The solution runs through a full request → lookup → order/approval flow in the mocked environment, not just isolated pieces.
- **Solving the problem and user need** (20%) – how Precisely the agent matches what the buyer actually asked for, with the least manual correction needed.
- **Autonomy and controls** (20%) – Quality of the guardrails design. What the agent can decide alone, what needs human sign-off, and how decisions are logged and auditable.
- **Robustness to exception situations** (15%) – Handling of partial availability, substitutions and delivery constraints beyond the happy path.
- **Openness and credible path toward production** (15%) – Open, documented standards rather than a proprietary format, clear visibility of assumptions, well-justified technical choices, and a credible view of next development steps

## Prizes

- **1st place:** 4 000€
- **2nd place:** 2 000€
- **3rd place:** 1 000€
