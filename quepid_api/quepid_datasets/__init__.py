"""Loaders for public relevance datasets, as Quepid cases.

Three commands: ``create_case`` makes an empty case -- configured by its own
flags, not by any dataset -- ``load_dataset`` fills one with queries and
judgements, ``list_cases`` says which cases exist. Installed only so Django finds them. Owns no models, no HTTP surface
and no database access: they are clients of this project's own REST API, so they
work against any deployment of it and double as a high-volume exercise of that
API (see ``load_dataset``'s docstring).

The name is deliberate: an app directory called ``datasets`` would shadow the
HuggingFace ``datasets`` distribution process-wide (see CLAUDE.md, "Naming
apps"), and that package is a plausible future dependency here.
"""
