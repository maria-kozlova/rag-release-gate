# spike/ — T01 throwaway probes

Decision-making code, not project code. **Nothing here graduates to `src/`.**

Results: [`FINDINGS.md`](FINDINGS.md).

```powershell
uv run python probe1_chat.py          # usage.cost inline
uv run python probe2_routing.py       # what the echoed `model` field means
uv run python probe3_embeddings.py    # dimension + cost reporting
uv run python probe4_structured.py    # response_format json_schema, both models
uv run python probe5_deepeval.py --path a|b|c
uv run python probe6_verify.py <generation-id> ...
```

Needs `OPENROUTER_API_KEY` in the repo-root `.env`. Total spend for a full pass: ~$0.011.
