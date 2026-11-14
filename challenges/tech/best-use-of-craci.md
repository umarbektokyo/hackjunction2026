# Best use of CRACI

**By:** Craci · **Type:** Tech challenge · **Track:** AI Infrastructure Track By Verda · **Tags:** General

**Page:** https://hackjunction.app/participate/45/tech-challenges/42 · **Website:** https://craci.com/

## Make every build your first line of defence.

### Description
Build anything you can imagine at Junction 2026, even a project made mainly for another challenge: as long as its CI/CD runs on CRACI, you can submit it to this challenge too. Switch a GitHub Actions job to runs-on: craci and every build records exactly what goes into your software, exposes that data through the CRACI API, and can fix vulnerabilities automatically with AI grounded in that exact build data. Treat all of this as raw material, not a checklist: an agent that patches your app while you sleep, a live map of everything the internet ships into your code, a tool that catches a malicious package the moment a build pulls it in, or something we have never thought of. Attackers now exploit new vulnerabilities within about a day, so the boldest ideas for software that defends itself will win. Surprise us.

### Mentors from CRACI's founding and engineering team
Juho Niemi (CEO), Dennis Marttinen (CTO), Petteri Pulkkinen (CISO), Veeti Poutsalo (Software Engineer) and Roope Ripatti (Forward Deployed Engineer). Between them they cover CI/CD and build systems, software supply chain security, vulnerability management, AI-driven automated fixing and the CRACI API.

Find the CRACI team at the CRACI booth throughout the event!

## Resources

Every team gets free access to the CRACI platform for the whole event, CI/CD build minutes included. CRACI runners are GitHub Actions compatible, so you can keep your existing workflows and switch a job over in one line. As your builds run, CRACI records every external dependency they pull in and produces verifiable CycloneDX SBOMs, including packages restored from caches, and AI fixes can patch vulnerabilities automatically based on that exact build data. Everything is open to you through the CRACI API, and our docs ship with agent skills so you can work with them in your AI coding tools. Our whole team is on site to help you get set up and to go deep on supply chain security.

### List of technologies that we are bringing:
– Free access to the CRACI platform during the event (platform.craci.com)
– CI/CD build minutes on CRACI's GitHub Actions-compatible runners
– Build-time CycloneDX SBOMs with completeness data per job and per cache
– AI fixes: automated vulnerability fixes grounded in exact build data
– The CRACI API: SBOMs, OCI image and cache provenance, network traces, job logs and compute usage
– Documentation, examples and agent skills: https://docs.craci.com/
– Five mentors from the CRACI team on site all weekend

## Claim your free compute

Every team gets 1000€ credits to the CRACI platform for the whole event. These can be used for CI/CD or any compute need you require. Setup takes about ten minutes.

### 1. Get your invite code

You need the Junction invite code to create your team's organization on CRACI. Get it either way:

- **Discord:** Ask in the `#craci` channel on the Junction Discord.
- **CRACI booth:** Come say hi. We'll give you the code and help with setup on the spot.

Only one person per team needs to do steps 2 to 4. Invite your teammates afterwards.

### 2. Sign up and create your organization

1. Go to [platform.craci.com](https://platform.craci.com) and sign up.
2. Create an organization for your team and enter the Junction invite code.

### 3. Connect GitHub

1. In CRACI, go to **Settings → Builds** and start the **Install GitHub** flow.
2. CRACI walks you through creating its GitHub App and installing it on your GitHub organization or account.
3. Grant the App access to the repositories you'll build: all repositories, or a selected set.
4. Wait until the connection shows **configured**.

You can change repository access later on GitHub under **Settings → GitHub Apps → CRACI → Configure**.

### 4. Run your first build on CRACI

After connecting the app, any workflow file with runs-on: craci will be running on the CRACI platform. The default runner size is 2 vCPUs and 6GB RAM. 

```yaml
jobs:
  build:
    runs-on: craci 
    steps:
      - uses: actions/checkout@v4
      - run: make build
```

Push, and the job runs on CRACI. Open the build in the platform to see what it pulled in.

Need a bigger machine? Add the setup step first:

```yaml
    steps:
      - uses: cracicorp/setup@v1
        with:
          size: "8"   # 1–32 units; each unit is 1 vCPU and 3 GB RAM. Default is 2.
      - uses: actions/checkout@v4
```

You can also point your agent at our migration skill for migrating old workflows or when creating new ones: https://docs.craci.com/skills/craci/SKILL.md

### 5. Get an API token

An organization admin can create a token under **Settings → API tokens**. The token is shown only once, so store it somewhere safe. Call the API at `https://api.craci.com` with `Authorization: Bearer $CRACI_API_TOKEN`. The full OpenAPI spec is at [api.craci.com/openapi.json](https://api.craci.com/openapi.json).

## Resources

If you or your agent needs more info, check out [docs.craci.com](https://docs.craci.com/) or come yap with us at the booth! (3rd next to the stage)

## Judging criteria

- **Technical depth** (50%)
- **How creatively you use CRACI's features** (50%) – SBOMs, AI fixes, provenance, network traces and the API. Original ideas we have not seen before score highest, so do not just add runs-on: Craci to a project and stop there.

## Prizes

- **1st Team:** LEGO set for each team member
- **2nd Team:** 24-pack of Red Bull for each team member
- **3rd Team:** invite to the CRACI x OpenAI lunch event during Slush.
- **Top 5 Teams:** Each of the top 5 teams receives 50,000 CRACI CI/CD build minutes per team member, plus the opportunity to interview for a job at CRACI.
