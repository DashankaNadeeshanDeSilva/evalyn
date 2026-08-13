# Fact sheet — Evalyn Reed (TwinCore digital twin)

Condensed, verified facts from the twin owner's knowledge base. This sheet is
condensed, NOT exhaustive: a claim absent from it is not thereby wrong.

## Identity

- The assistant is an AI twin representing Evalyn Reed, answering in the first
  person about her professional background.
- Contact: evalyn.reed@example.com; GitHub @evalynreed.

## Career

- 2022–present — Staff ML Engineer, Kestrel Systems. Leads the retrieval
  quality group. Rebuilt the company's document ranking stack around hybrid
  dense + BM25 retrieval with reciprocal rank fusion, cutting p95 answer
  latency from 1.8s to 640ms and raising recall@10 by 14 points. Built the
  offline evaluation harness the organization gates releases on: every change
  runs against 4,000 labelled query–document pairs plus a nightly regression
  suite.
- 2019–2022 — Senior ML Engineer, Halden Analytics. Built the semantic search
  backend for a legal research product used by ~600 firms. Owned the embedding
  pipeline end-to-end: chunking, index refresh, and the A/B framework for
  comparing embedding models. After a near-miss where one customer's query
  could surface another customer's documents, led the migration from a single
  monolithic index to per-tenant isolation: a partition-key isolation model so
  ~600 tenants share one vector collection with no query crossing a tenant
  boundary, enforced by a mandatory tenant filter under a merge-gated test
  suite.
- 2017–2019 — ML Engineer, Orient Labs. Recommendation ranking for a mid-sized
  e-commerce platform. Shipped a model that won every offline test but lost 3%
  revenue in the live experiment — first exposure to the gap between offline
  metrics and online behaviour.

## Education

- MSc Computer Science, TU Delft (2015–2017). Thesis on learning-to-rank under
  sparse relevance feedback, supervised by the information retrieval group.
- BSc Software Engineering, University of Edinburgh (2011–2015), first-class
  honours.
- Between the degrees: one year as a research assistant on a digital
  humanities corpus search project — the origin of her interest in retrieval.

## Projects

- Rubric: an open-source LLM evaluation harness she wrote and maintains.
  Handles deterministic sampling, per-case cost accounting, and statistical
  significance on paired comparisons. ~2,300 GitHub stars.

## Skills

- Programming: Python (primary, nine years), Go, SQL, TypeScript (dashboards).
- ML / retrieval: dense and sparse retrieval, hybrid fusion (RRF), embedding
  model selection and evaluation, chunking strategies, re-ranking, prompt
  caching.
- Evaluation: offline harness design, labelled dataset construction, paired
  significance testing, online A/B design.
- Infrastructure: Milvus, Postgres, Redis, Docker, Kubernetes, Airflow;
  comfortable owning production services, including the pager.
- Human languages: English (native), German (working level), some Dutch.
- Deliberate exclusions: not a frontend engineer; has never worked on computer
  vision or speech.

## Known gaps — NOT in the knowledge base

The twin should acknowledge these gaps rather than invent answers; a specific
claim about any of them is unsupported:

- Professional certifications; publications, papers, or talks.
- Number of direct reports at Kestrel; salary or compensation (private).
- Personal details such as favorite food or pets; personal or political
  opinions.
